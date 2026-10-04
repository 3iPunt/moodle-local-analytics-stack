"""Hardened per-request DuckDB connections and guarded query execution."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterable, Mapping

import duckdb

from app.guard import validate_sql

BASE_SCHEMA = "base"
DEFAULT_TIMEOUT_S = 30.0

_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


class QueryTimeout(RuntimeError):
    """The query exceeded its time budget and was interrupted."""


def _ident(name: str) -> str:
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return name


def _course_ids(course_ids: Iterable[int]) -> list[int]:
    ids = list(course_ids)
    for cid in ids:
        if not isinstance(cid, int) or isinstance(cid, bool):
            raise ValueError(f"course id must be an int, got {cid!r}")
    return ids


def open_query_connection(
    db_path: str,
    course_ids: Iterable[int],
    tables_with_course_id: Mapping[str, str | None],
) -> duckdb.DuckDBPyConnection:
    """Open the export read-only and expose filtered TEMP VIEWS.

    ``tables_with_course_id`` maps each view name to the column used for
    course filtering in ``base.<view>``, or ``None`` to expose it unfiltered.
    An empty ``course_ids`` list yields views with no rows.
    """
    ids = _course_ids(course_ids)
    predicate_values = ", ".join(str(i) for i in ids)
    con = duckdb.connect(
        db_path,
        read_only=True,
        config={"enable_external_access": False, "lock_configuration": True},
    )
    try:
        for view, column in tables_with_course_id.items():
            source = f"{BASE_SCHEMA}.{_ident(view)}"
            if column is None:
                where = ""
            elif ids:
                where = f" WHERE {_ident(column)} IN ({predicate_values})"
            else:
                where = " WHERE FALSE"
            con.execute(f"CREATE TEMP VIEW {view} AS SELECT * FROM {source}{where}")
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
