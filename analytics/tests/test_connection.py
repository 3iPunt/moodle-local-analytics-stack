import time

import duckdb
import pytest

from app.db import QueryTimeout, open_query_connection, run_guarded
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


def test_base_schema_reachable_on_connection_but_guard_rejects(db_path):
    con = open_query_connection(db_path, [1], TABLES)
    assert con.execute("SELECT count(*) FROM base.course").fetchone()[0] == 3
    with pytest.raises(GuardError) as info:
        run_guarded(con, "SELECT * FROM base.course", ALLOWED, 100)
    assert info.value.reason == "qualified_table"


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
        "ATTACH ':memory:' AS other",
        "ATTACH '/tmp/analytics_guard_other.duckdb' AS other",
        "COPY (SELECT 1) TO '/tmp/analytics_guard_test.csv'",
        "INSTALL mysql",
        "LOAD mysql",
        "CREATE TABLE t AS SELECT 1",
        "CREATE TABLE base.t AS SELECT 1",
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
