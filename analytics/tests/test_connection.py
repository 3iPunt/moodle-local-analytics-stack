import os
import threading
import time

import duckdb
import pytest

from app.db import QueryTimeout, ReaderLimits, open_query_connection, run_guarded
from app.guard import GuardError
from tests.conftest import ALLOWED, TABLES


def test_views_only_expose_requested_courses(db_path):
    con = open_query_connection(db_path, [1, 3], TABLES)
    assert sorted(r[0] for r in con.execute("SELECT course_id FROM course").fetchall()) == [1, 3]
    assert {r[0] for r in con.execute("SELECT DISTINCT course_id FROM participant").fetchall()} == {1, 3}


def test_empty_course_list_returns_no_rows(db_path):
    con = open_query_connection(db_path, [], TABLES)
    cols, rows, _ = run_guarded(con, "SELECT * FROM participant", ALLOWED, 100)
    assert rows == []
    assert cols == ["course_id", "user_ref", "role", "last_access"]


def test_non_integer_course_ids_rejected(db_path):
    with pytest.raises(ValueError):
        open_query_connection(db_path, ["1) OR (1=1"], TABLES)


def test_invalid_table_name_rejected(db_path):
    with pytest.raises(ValueError):
        open_query_connection(db_path, [1], {"course; DROP": "course_id"})


def test_unfiltered_table(db_path):
    con = open_query_connection(db_path, [1], {"course": None})
    assert con.execute("SELECT count(*) FROM course").fetchone()[0] == 3


def test_other_courses_never_exist_on_the_connection(db_path):
    con = open_query_connection(db_path, [1], TABLES)
    for sql in ("SELECT count(*) FROM base.course", "SELECT count(*) FROM src.course"):
        with pytest.raises(duckdb.CatalogException, match="does not exist"):
            con.execute(sql)
    with pytest.raises(duckdb.BinderException, match='Catalog "src" does not exist'):
        con.execute("SELECT count(*) FROM src.base.course")
    assert con.execute("SELECT count(*) FROM participant").fetchone()[0] == 5
    assert con.execute("SELECT DISTINCT course_id FROM participant").fetchall() == [(1,)]
    with pytest.raises(GuardError) as info:
        run_guarded(con, "SELECT * FROM base.course", ALLOWED, 100)
    assert info.value.reason == "qualified_table"


def test_comments_are_copied_for_the_prompt(db_path):
    src = duckdb.connect(db_path)
    src.execute("COMMENT ON TABLE base.course IS 'Courses.'")
    src.execute("COMMENT ON COLUMN base.course.shortname IS 'Short code.'")
    src.close()
    con = open_query_connection(db_path, [1], TABLES)
    assert con.execute("SELECT comment FROM duckdb_tables() WHERE table_name = 'course'").fetchone()[0] == "Courses."
    assert con.execute(
        "SELECT comment FROM duckdb_columns() WHERE table_name = 'course' AND column_name = 'shortname'"
    ).fetchone()[0] == "Short code."


def test_resource_limits_are_set_and_locked(db_path, tmp_path):
    limits = ReaderLimits(memory_limit="256MB", threads=1, max_temp_directory_size="0B")
    con = open_query_connection(db_path, [1], TABLES, limits=limits)
    memory, threads, temp_size, external = con.execute(
        "SELECT current_setting('memory_limit'), current_setting('threads'), "
        "current_setting('max_temp_directory_size'), current_setting('enable_external_access')"
    ).fetchone()
    assert memory == "244.1 MiB" and threads == 1 and temp_size == "0 bytes" and external is False
    for sql in ("SET memory_limit = '8GB'", "SET threads = 8", "RESET memory_limit", "SET enable_external_access = true"):
        with pytest.raises(duckdb.InvalidInputException, match="locked"):
            con.execute(sql)


def test_reader_limits_from_env():
    limits = ReaderLimits.from_env({"DUCKDB_MEMORY_LIMIT": "1GB", "DUCKDB_THREADS": "4", "DUCKDB_MAX_TEMP_SIZE": "64MB"})
    assert limits == ReaderLimits(memory_limit="1GB", threads=4, max_temp_directory_size="64MB")
    assert ReaderLimits.from_env({}) == ReaderLimits()
    assert ReaderLimits() == ReaderLimits(memory_limit="512MB", threads=2, max_temp_directory_size="0B")
    for bad in ({"DUCKDB_THREADS": "0"}, {"DUCKDB_MEMORY_LIMIT": "1GB'; SET x"}):
        with pytest.raises(ValueError):
            ReaderLimits.from_env(bad)


def test_writes_only_touch_the_private_copy(db_path):
    """DROP or CREATE on a request connection changes nothing outside it; the guard rejects them anyway."""
    con = open_query_connection(db_path, [1], TABLES)
    con.execute("DROP TABLE participant")
    con.execute("CREATE TABLE t AS SELECT 1")
    con.execute("ATTACH ':memory:' AS scratch")
    con.close()
    with pytest.raises(GuardError):
        run_guarded(open_query_connection(db_path, [1], TABLES), "DROP TABLE participant", ALLOWED, 10)
    fresh = open_query_connection(db_path, [1], TABLES)
    assert fresh.execute("SELECT count(*) FROM participant").fetchone()[0] == 5
    check = duckdb.connect(db_path, read_only=True)
    assert check.execute("SELECT count(*) FROM base.participant").fetchone()[0] == 15
    check.close()


def test_new_connection_sees_a_swapped_file_while_an_old_one_is_open(db_path, tmp_path):
    old = open_query_connection(db_path, [1], TABLES)
    replacement = tmp_path / "next.duckdb"
    src = duckdb.connect(str(replacement))
    src.execute("CREATE SCHEMA base")
    src.execute("CREATE TABLE base.course AS SELECT 1 AS course_id, 'new' AS shortname, 'New' AS fullname")
    src.execute("CREATE TABLE base.participant AS SELECT 1 AS course_id, 'x' AS user_ref, 'student' AS role, NULL AS last_access")
    src.close()
    os.replace(replacement, db_path)

    results = []

    def request():
        c = open_query_connection(db_path, [1], TABLES)
        results.append(c.execute("SELECT shortname FROM course").fetchone()[0])
        c.close()

    threads = [threading.Thread(target=request) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results == ["new", "new"]
    assert old.execute("SELECT shortname FROM course").fetchone()[0] == "c1"
    old.close()


def test_run_guarded_returns_columns_rows_elapsed(db_path):
    con = open_query_connection(db_path, [2], TABLES)
    cols, rows, elapsed = run_guarded(con, "SELECT course_id, shortname FROM course", ALLOWED, 10)
    assert cols == ["course_id", "shortname"]
    assert rows == [(2, "c2")]
    assert elapsed >= 0


@pytest.mark.parametrize(
    "sql",
    [
        "SET enable_external_access = true",
        "SELECT * FROM read_csv('/etc/passwd')",
        "ATTACH '/tmp/analytics_guard_other.duckdb' AS other",
        "COPY (SELECT 1) TO '/tmp/analytics_guard_test.csv'",
        "INSTALL mysql",
        "LOAD mysql",
        "SELECT * FROM 'other.duckdb'",
    ],
)
def test_connection_hardening(db_path, sql):
    con = open_query_connection(db_path, [1], TABLES)
    with pytest.raises(duckdb.Error):
        con.execute(sql)


def test_timeout_interrupts_heavy_query(db_path):
    con = open_query_connection(db_path, [1], TABLES)
    start = time.monotonic()
    with pytest.raises(QueryTimeout):
        run_guarded(
            con,
            "SELECT count(*) FROM range(10000000000) a, range(1000) b",
            ALLOWED,
            10,
            timeout_s=0.5,
        )
    assert time.monotonic() - start < 5
