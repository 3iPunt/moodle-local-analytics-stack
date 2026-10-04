"""Export a pseudonymised subset of Moodle into ``/data/moodle.duckdb``.

``views.sql`` is the only place that holds business logic. It reads Moodle
through a catalog alias ``m`` and creates the ``base.*`` tables. The two export
formats differ only in how ``m`` is provided:

* ``duckdb`` (default): ``m`` is the live MySQL database attached READ_ONLY
  with DuckDB's mysql_scanner extension (installed at image build time).
* ``parquet``: PyMySQL streams the whitelisted columns in ``SOURCE_COLUMNS``
  into Parquet staging files (pyarrow), and ``m`` is an in-memory catalog of
  views over them. The staging files hold raw Moodle ids, so they live in a
  temporary directory removed after the build. The pseudonymised ``base``
  tables are then also written to ``/data/parquet/<table>.parquet``.

``views.sql`` casts every output column, so both paths give the same schema.
``SOURCE_COLUMNS`` doubles as a whitelist: no name, email, username or IP
column is ever read in parquet mode, and the mysql path only reads the columns
views.sql references (projection pushdown).

Pseudonymisation: ``user_ref = md5(userid || salt)``. The salt is substituted
into a TEMP macro, which DuckDB never persists, and is scrubbed from errors.

Publishing: the build writes ``moodle.duckdb.tmp``, checkpoints it, closes it
and ``os.replace``s it onto ``moodle.duckdb``. Readers already holding the old
file keep reading the old inode until they close; new connections see the new
file. DuckDB caches one database instance per path inside a process, so a
``duckdb.connect(path)`` opened while an old one is still open reuses the old
snapshot: direct readers (/health, /schema, CLI) open a connection per call and
close it. Query connections (app/db.py) ATTACH the file into a private in-memory
database instead, which bypasses that cache and always sees the latest file.

An exclusive ``flock`` on ``/data/.export.lock`` serialises exports across
threads, processes and containers that share the volume.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path

import duckdb

from app.config import Settings
from app.schema import TABLES

log = logging.getLogger("analytics.export")

VIEWS_SQL = Path(__file__).resolve().parent.parent / "views.sql"
LOCK_FILE = ".export.lock"
FETCH_BATCH = 50_000

SOURCE_COLUMNS: dict[str, tuple[str, ...]] = {
    "mdl_course": ("id", "shortname", "fullname", "startdate", "visible", "enablecompletion", "format"),
    "mdl_user": ("id", "deleted", "lastaccess"),
    "mdl_enrol": ("id", "courseid", "status"),
    "mdl_user_enrolments": ("id", "enrolid", "userid", "status", "timestart", "timecreated"),
    "mdl_context": ("id", "contextlevel", "instanceid"),
    "mdl_role": ("id", "shortname"),
    "mdl_role_assignments": ("id", "roleid", "contextid", "userid"),
    "mdl_user_lastaccess": ("id", "userid", "courseid", "timeaccess"),
    "mdl_logstore_standard_log": (
        "id", "courseid", "userid", "timecreated", "origin", "action", "contextlevel", "contextinstanceid", "anonymous",
    ),
    "mdl_modules": ("id", "name"),
    "mdl_course_modules": ("id", "course", "module", "instance", "section", "visible", "completion", "deletioninprogress"),
    "mdl_course_sections": ("id", "section"),
    "mdl_assign": ("id", "course", "name", "duedate"),
    "mdl_quiz": ("id", "name", "timeclose"),
    "mdl_page": ("id", "name"),
    "mdl_forum": ("id", "name"),
    "mdl_url": ("id", "name"),
    "mdl_resource": ("id", "name"),
    "mdl_book": ("id", "name"),
    "mdl_label": ("id", "name"),
    "mdl_course_modules_completion": ("id", "coursemoduleid", "userid", "completionstate", "timemodified"),
    "mdl_course_completions": ("id", "userid", "course", "timecompleted"),
    "mdl_grade_items": ("id", "courseid", "itemname", "itemtype", "itemmodule", "iteminstance", "grademax", "grademin"),
    "mdl_grade_grades": ("id", "itemid", "userid", "finalgrade", "rawgrade", "timemodified"),
    "mdl_assign_submission": ("id", "assignment", "userid", "status", "timemodified", "latest"),
}

_PLACEHOLDER_RE = re.compile(r"\{(salt|now_epoch)\}")

__all__ = [
    "TABLES", "SOURCE_COLUMNS", "ExportBusy", "ExportError", "ExportResult", "attach_mysql", "attach_parquet_staging",
    "build_database", "export", "export_lock", "publish", "render_views_sql", "run_views", "sql_literal", "user_ref",
]


class ExportBusy(RuntimeError):
    """Another export holds the lock."""


class ExportError(RuntimeError):
    """The export failed. The message never contains secrets."""


@dataclass(frozen=True)
class ExportResult:
    row_counts: dict[str, int]
    duration_ms: float
    exported_at: str
    source: str

    def to_dict(self) -> dict:
        return asdict(self)


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def user_ref(userid: int, salt: str) -> str:
    """Python twin of the ``pseudo()`` macro in views.sql."""
    return hashlib.md5(f"{int(userid)}{salt}".encode()).hexdigest()


def render_views_sql(template: str, salt: str, now_epoch: int) -> str:
    if not isinstance(now_epoch, int) or isinstance(now_epoch, bool):
        raise ValueError("now_epoch must be an int")
    values = {"salt": sql_literal(salt), "now_epoch": str(now_epoch)}
    return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], template)


def _scrub(message: str, *secrets: str) -> str:
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    return message


def run_views(con: duckdb.DuckDBPyConnection, salt: str, now_epoch: int, source: str) -> dict[str, int]:
    """Run views.sql on a connection where ``m`` is attached. Returns row counts."""
    sql = render_views_sql(VIEWS_SQL.read_text(encoding="utf-8"), salt, now_epoch)
    for i, statement in enumerate(duckdb.extract_statements(sql), start=1):
        try:
            con.execute(statement)
        except duckdb.Error as err:
            raise ExportError(f"views.sql statement {i} failed: {_scrub(str(err), salt)}") from None
    counts = {t: con.execute(f"SELECT count(*) FROM base.{t}").fetchone()[0] for t in TABLES}
    con.execute(
        "INSERT INTO base.export_meta VALUES (make_timestamp(CAST(? AS BIGINT) * 1000000), ?, ?)",
        [now_epoch, source, json.dumps(counts)],
    )
    return counts


def _remove_db(path: Path) -> None:
    for p in (path, path.with_name(path.name + ".wal")):
        p.unlink(missing_ok=True)


def build_database(
    target: Path,
    attach: Callable[[duckdb.DuckDBPyConnection], None],
    salt: str,
    now_epoch: int,
    source: str,
) -> dict[str, int]:
    """Create ``target`` from scratch with an unlocked connection."""
    target = Path(target)
    _remove_db(target)
    con = duckdb.connect(str(target))
    try:
        attach(con)
        counts = run_views(con, salt, now_epoch, source)
        con.execute("DETACH m")
        con.execute("CHECKPOINT")
    finally:
        con.close()
    return counts


def publish(tmp: Path, final: Path) -> None:
    """Atomically replace ``final`` with the finished build ``tmp``."""
    final.with_name(final.name + ".wal").unlink(missing_ok=True)
    os.replace(tmp, final)


@contextlib.contextmanager
def export_lock(data_dir: Path) -> Iterator[None]:
    with open(Path(data_dir) / LOCK_FILE, "a+") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ExportBusy("an export is already running") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# --- sources -----------------------------------------------------------------


def attach_mysql(con: duckdb.DuckDBPyConnection, settings: Settings) -> None:
    dsn = (
        f"host={settings.db_host} port={settings.db_port} user={settings.db_user} "
        f"password={settings.db_password} database={settings.db_name}"
    )
    try:
        con.execute("LOAD mysql")
        # Keep TINYINT(1) as integers: completionstate and completion use values above 1.
        con.execute("SET mysql_tinyint1_as_boolean = false")
        con.execute(f"ATTACH {sql_literal(dsn)} AS m (TYPE mysql_scanner, READ_ONLY)")
    except duckdb.Error as err:
        raise ExportError(f"cannot attach MySQL: {_scrub(str(err), settings.db_password)}") from None


def stage_parquet(settings: Settings, staging_dir: Path) -> dict[str, int]:
    """Dump the whitelisted Moodle columns to ``<staging_dir>/<table>.parquet``."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import pymysql
    from pymysql.constants import FIELD_TYPE

    ints = {FIELD_TYPE.TINY, FIELD_TYPE.SHORT, FIELD_TYPE.LONG, FIELD_TYPE.LONGLONG, FIELD_TYPE.INT24, FIELD_TYPE.YEAR}
    floats = {FIELD_TYPE.DECIMAL, FIELD_TYPE.NEWDECIMAL, FIELD_TYPE.FLOAT, FIELD_TYPE.DOUBLE}

    def arrow_type(code: int) -> pa.DataType:
        return pa.int64() if code in ints else pa.float64() if code in floats else pa.string()

    def convert(value):
        return float(value) if isinstance(value, Decimal) else value

    try:
        conn = pymysql.connect(
            host=settings.db_host,
            port=settings.db_port,
            user=settings.db_user,
            password=settings.db_password,
            database=settings.db_name,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.SSCursor,
        )
    except pymysql.MySQLError as err:
        raise ExportError(f"cannot connect to MySQL: {_scrub(str(err), settings.db_password)}") from None
    counts = {}
    try:
        for table, columns in SOURCE_COLUMNS.items():
            with conn.cursor() as cur:
                cur.execute(f"SELECT {', '.join(f'`{c}`' for c in columns)} FROM `{table}`")
                schema = pa.schema([(d[0], arrow_type(d[1])) for d in cur.description])
                n = 0
                with pq.ParquetWriter(staging_dir / f"{table}.parquet", schema) as writer:
                    while batch := cur.fetchmany(FETCH_BATCH):
                        cols = list(zip(*batch))
                        arrays = [pa.array([convert(v) for v in col], type=f.type) for col, f in zip(cols, schema)]
                        writer.write_table(pa.Table.from_arrays(arrays, schema=schema))
                        n += len(batch)
                counts[table] = n
    finally:
        conn.close()
    return counts


def attach_parquet_staging(con: duckdb.DuckDBPyConnection, staging_dir: Path) -> None:
    con.execute("ATTACH ':memory:' AS m")
    for table in SOURCE_COLUMNS:
        path = sql_literal(str(Path(staging_dir) / f"{table}.parquet"))
        con.execute(f"CREATE VIEW m.{table} AS SELECT * FROM read_parquet({path})")


def write_parquet_outputs(db_file: Path, out_dir: Path) -> None:
    """Write every ``base`` table to ``out_dir/<table>.parquet`` and swap the directory in."""
    tmp_dir = out_dir.with_name(out_dir.name + ".tmp")
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir()
    con = duckdb.connect(str(db_file), read_only=True)
    try:
        for table in (*TABLES, "export_meta"):
            con.execute(f"COPY base.{table} TO {sql_literal(str(tmp_dir / (table + '.parquet')))} (FORMAT parquet)")
    finally:
        con.close()
    old = out_dir.with_name(out_dir.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    if out_dir.exists():
        out_dir.rename(old)
    tmp_dir.rename(out_dir)
    shutil.rmtree(old, ignore_errors=True)


# --- orchestration -----------------------------------------------------------


def export(settings: Settings, now_epoch: int | None = None) -> ExportResult:
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    with export_lock(data_dir):
        start = time.perf_counter()
        now = int(time.time()) if now_epoch is None else now_epoch
        tmp = data_dir / (settings.db_path.name + ".tmp")
        try:
            if settings.export_format == "parquet":
                source = "parquet"
                with tempfile.TemporaryDirectory(dir=data_dir, prefix=".staging-") as staging:
                    stage_parquet(settings, Path(staging))
                    counts = build_database(
                        tmp, lambda c: attach_parquet_staging(c, Path(staging)), settings.salt, now, source
                    )
                write_parquet_outputs(tmp, data_dir / "parquet")
            else:
                source = "mysql"
                counts = build_database(tmp, lambda c: attach_mysql(c, settings), settings.salt, now, source)
            publish(tmp, settings.db_path)
        except Exception:
            _remove_db(tmp)
            raise
        duration_ms = (time.perf_counter() - start) * 1000.0
    exported_at = dt.datetime.fromtimestamp(now, dt.timezone.utc).replace(tzinfo=None).isoformat()
    log.info("export finished source=%s duration_ms=%.0f rows=%s", source, duration_ms, json.dumps(counts))
    return ExportResult(row_counts=counts, duration_ms=round(duration_ms, 1), exported_at=exported_at, source=source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Moodle to DuckDB and print row counts.")
    parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        result = export(Settings.from_env())
    except ExportBusy as err:
        print(f"export skipped: {err}", file=sys.stderr)
        return 2
    except ExportError as err:
        print(f"export failed: {err}", file=sys.stderr)
        return 1
    width = max(len(t) for t in result.row_counts)
    for table, n in result.row_counts.items():
        print(f"{table:<{width}}  {n:>8}")
    print(f"source={result.source} exported_at={result.exported_at}Z duration_ms={result.duration_ms:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
