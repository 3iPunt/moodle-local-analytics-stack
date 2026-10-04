"""Per-request DuckDB connections scoped to a course list, and guarded query execution.

Each request gets a private in-memory database. The export is attached
READ_ONLY only long enough to copy the rows of the requested courses into
plain tables, then detached. Rows of other courses never exist on the
connection, so a query that slips past the SQL guard still cannot read them.
Afterwards external access is disabled and the configuration is locked, with
memory, thread and temp-space limits.

The connection is writable, but only its private copy: a DROP or CREATE that
got past the guard would change nothing outside the request.

ATTACH does not go through DuckDB's per-path instance cache (which applies to
``duckdb.connect(path)``), so a request opened after an export swap reads the
new file even while older connections are still open.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import duckdb

from app.guard import validate_sql

BASE_SCHEMA = "base"
QUERY_SCHEMA = "main"
DEFAULT_TIMEOUT_S = 30.0
TEMP_DIR_NAME = ".duckdb-tmp"

# Readers that open the export file directly (/health, /schema, CLI tools) all use this
# config: DuckDB caches one instance per path and refuses a second connection to the
# same path with a different configuration.
READER_CONFIG = {"enable_external_access": False, "lock_configuration": True}

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
_SIZE_RE = re.compile(r"^[0-9]+(\.[0-9]+)?\s*(B|KB|MB|GB|TB|KiB|MiB|GiB|TiB)?$")


class QueryTimeout(RuntimeError):
    """The query exceeded its time budget and was interrupted."""


@dataclass(frozen=True)
class ReaderLimits:
    memory_limit: str = "512MB"
    threads: int = 2
    # 0B: a query that does not fit in memory_limit fails instead of spilling to disk.
    max_temp_directory_size: str = "0B"

    def __post_init__(self) -> None:
        for value in (self.memory_limit, self.max_temp_directory_size):
            if not _SIZE_RE.match(value):
                raise ValueError(f"invalid DuckDB size: {value!r}")
        if not isinstance(self.threads, int) or self.threads < 1:
            raise ValueError("threads must be a positive integer")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> ReaderLimits:
        env = os.environ if env is None else env
        defaults = cls()
        try:
            threads = int(env.get("DUCKDB_THREADS", "") or defaults.threads)
        except ValueError as err:
            raise ValueError("DUCKDB_THREADS must be an integer") from err
        return cls(
            memory_limit=env.get("DUCKDB_MEMORY_LIMIT", "") or defaults.memory_limit,
            threads=threads,
            max_temp_directory_size=env.get("DUCKDB_MAX_TEMP_SIZE", "") or defaults.max_temp_directory_size,
        )


def _ident(name: str) -> str:
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return name


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _course_ids(course_ids: Iterable[int]) -> list[int]:
    ids = list(course_ids)
    for cid in ids:
        if not isinstance(cid, int) or isinstance(cid, bool):
            raise ValueError(f"course id must be an int, got {cid!r}")
    return ids


def _copy_comments(con: duckdb.DuckDBPyConnection, tables: list[str]) -> None:
    for table, comment in con.execute(
        "SELECT table_name, comment FROM duckdb_tables() "
        "WHERE database_name = 'src' AND schema_name = ? AND comment IS NOT NULL",
        [BASE_SCHEMA],
    ).fetchall():
        if table in tables:
            con.execute(f"COMMENT ON TABLE {table} IS {_literal(comment)}")
    for table, column, comment in con.execute(
        "SELECT table_name, column_name, comment FROM duckdb_columns() "
        "WHERE database_name = 'src' AND schema_name = ? AND comment IS NOT NULL",
        [BASE_SCHEMA],
    ).fetchall():
        if table in tables:
            con.execute(f"COMMENT ON COLUMN {table}.{_quoted(column)} IS {_literal(comment)}")


def open_query_connection(
    db_path: str,
    course_ids: Iterable[int],
    tables_with_course_id: Mapping[str, str | None],
    limits: ReaderLimits | None = None,
) -> duckdb.DuckDBPyConnection:
    """Copy the requested courses of the export into a locked in-memory connection.

    ``tables_with_course_id`` maps each table name to the column used for
    course filtering in ``base.<table>``, or ``None`` to copy it whole. An
    empty ``course_ids`` list yields empty tables with the same columns.
    """
    ids = _course_ids(course_ids)
    tables = [_ident(t) for t in tables_with_course_id]
    limits = limits or ReaderLimits.from_env()
    temp_dir = Path(db_path).resolve().parent / TEMP_DIR_NAME
    con = duckdb.connect(":memory:")
    try:
        con.execute(f"SET memory_limit = {_literal(limits.memory_limit)}")
        con.execute(f"SET threads = {int(limits.threads)}")
        con.execute(f"SET temp_directory = {_literal(str(temp_dir))}")
        con.execute(f"SET max_temp_directory_size = {_literal(limits.max_temp_directory_size)}")
        con.execute(f"ATTACH {_literal(str(db_path))} AS src (READ_ONLY)")
        for table, column in tables_with_course_id.items():
            if column is None:
                where = ""
            elif ids:
                where = f" WHERE {_ident(column)} IN ({', '.join(str(i) for i in ids)})"
            else:
                where = " WHERE FALSE"
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM src.{BASE_SCHEMA}.{table}{where}")
        _copy_comments(con, tables)
        con.execute("DETACH src")
        con.execute("SET enable_external_access = false")
        con.execute("SET lock_configuration = true")
    except Exception:
        con.close()
        raise
    return con


def run_guarded(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    allowed_tables: set[str],
    max_rows: int,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[list[str], list[tuple], float]:
    """Validate ``sql`` and run it with a wall-clock timeout.

    Returns ``(columns, rows, elapsed_ms)``. Raises ``GuardError`` before
    execution and ``QueryTimeout`` when the query is interrupted.
    """
    final_sql = validate_sql(sql, allowed_tables, max_rows)
    timed_out = threading.Event()

    def _interrupt() -> None:
        timed_out.set()
        conn.interrupt()

    timer = threading.Timer(timeout_s, _interrupt)
    timer.daemon = True
    start = time.perf_counter()
    timer.start()
    try:
        cursor = conn.execute(final_sql)
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
    except duckdb.InterruptException as err:
        raise QueryTimeout(f"query exceeded {timeout_s:g}s and was cancelled") from err
    except duckdb.Error:
        if timed_out.is_set():
            raise QueryTimeout(f"query exceeded {timeout_s:g}s and was cancelled") from None
        raise
    finally:
        timer.cancel()
    return columns, rows, (time.perf_counter() - start) * 1000.0
