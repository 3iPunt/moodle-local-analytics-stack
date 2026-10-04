import pytest

from app.db import open_query_connection
from app.guard import GuardError, extract_sql_from_model_output, validate_sql
from tests.conftest import ALLOWED, TABLES


def ok(sql, max_rows=200):
    return validate_sql(sql, ALLOWED, max_rows)


def rejected(sql):
    with pytest.raises(GuardError) as info:
        ok(sql)
    return info.value


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM course",
        "select shortname from COURSE",
        "SELECT c.shortname, count(*) AS n FROM course c JOIN participant p ON p.course_id = c.course_id GROUP BY 1",
        "WITH x AS (SELECT course_id FROM participant) SELECT * FROM x",
        "SELECT course_id FROM course UNION SELECT course_id FROM participant",
        "SELECT course_id FROM course EXCEPT SELECT course_id FROM participant",
        "SELECT * FROM (SELECT course_id FROM course) AS sub",
        "SELECT * FROM course WHERE course_id IN (SELECT course_id FROM participant)",
        "SELECT * FROM course LIMIT 5",
        "SELECT 1",
        "SELECT * FROM range(10)",
        "WITH mdl_user AS (SELECT * FROM participant) SELECT * FROM mdl_user",
        "SELECT 'a;b' AS s FROM course",
    ],
)
def test_accepts_read_only_queries(sql, db_path):
    final = ok(sql)
    assert final.startswith("SELECT * FROM (")
    con = open_query_connection(db_path, [1, 2], TABLES)
    con.execute(final).fetchall()


def test_strips_fences_and_trailing_semicolon():
    out = ok("```sql\nSELECT * FROM course;\n```")
    assert out == "SELECT * FROM (SELECT * FROM course) AS q LIMIT 200"


def test_wraps_with_outer_limit():
    out = ok("SELECT * FROM course LIMIT 1000", max_rows=200)
    assert out.startswith("SELECT * FROM (")
    assert out.endswith(") AS q LIMIT 200")


def test_inner_limit_is_capped_on_execution(db_path):
    con = open_query_connection(db_path, [1, 2, 3], TABLES)
    rows = con.execute(validate_sql("SELECT * FROM participant LIMIT 1000", ALLOWED, 4)).fetchall()
    assert len(rows) == 4


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO course VALUES (9, 'x', 'y')",
        "UPDATE course SET shortname = 'x'",
        "DELETE FROM course",
        "MERGE INTO course USING participant ON course.course_id = participant.course_id WHEN MATCHED THEN DELETE",
        "CREATE TEMP VIEW v AS SELECT 1",
        "CREATE TABLE t AS SELECT * FROM course",
        "DROP TABLE course",
        "ALTER TABLE course ADD COLUMN x INT",
        "ATTACH 'x.db' AS y",
        "DETACH y",
        "COPY course TO '/tmp/x.csv'",
        "EXPORT DATABASE '/tmp/x'",
        "IMPORT DATABASE '/tmp/x'",
        "INSTALL mysql",
        "LOAD mysql",
        "PRAGMA version",
        "SET x=1",
        "RESET x",
        "CALL dbgen(sf=1)",
        "USE base",
        "EXECUTE p",
        "PREPARE p AS SELECT 1",
        "BEGIN TRANSACTION",
        "COMMIT",
        "DESCRIBE course",
        "SHOW TABLES",
        "SUMMARIZE course",
        "EXPLAIN SELECT 1",
        "CHECKPOINT",
    ],
)
def test_rejects_non_select_statements(sql):
    assert rejected(sql).reason in {"not_select", "parse_error"}


@pytest.mark.parametrize("sql", ["", "   ", "```sql\n```", ";"])
def test_rejects_empty(sql):
    assert rejected(sql).reason == "empty"


@pytest.mark.parametrize(
    "sql",
    ["SELECT 1; SELECT 2", "SELECT * FROM course; COPY course TO '/tmp/x.csv'", "SELECT 1;;"],
)
def test_rejects_multiple_statements(sql):
    assert rejected(sql).reason == "multiple_statements"


def test_rejects_select_into():
    assert rejected("SELECT * INTO t FROM course").reason == "select_into"


@pytest.mark.parametrize(
    "sql", ["SELECT * FROM base.course", "SELECT * FROM main.course", "SELECT * FROM memory.base.course"]
)
def test_rejects_qualified_tables(sql):
    assert rejected(sql).reason == "qualified_table"


@pytest.mark.parametrize(
    "sql", ["SELECT * FROM information_schema.tables", "SELECT * FROM pg_catalog.pg_tables"]
)
def test_rejects_system_catalogs(sql):
    assert rejected(sql).reason == "system_catalog"


@pytest.mark.parametrize(
    "sql", ['SELECT * FROM "base.course"', "SELECT * FROM 'x.parquet'", "SELECT * FROM (ATTACH 'x')"]
)
def test_rejects_quoted_or_garbage_names(sql):
    assert rejected(sql).reason == "unknown_table"


def test_unknown_table_message_is_actionable():
    err = rejected("SELECT * FROM mdl_user")
    assert err.reason == "unknown_table"
    assert "'mdl_user' is not available" in str(err)
    assert "course, participant" in str(err)


def test_cte_scope_does_not_leak():
    sql = "SELECT * FROM (WITH mdl_user AS (SELECT 1) SELECT * FROM mdl_user) s, mdl_user"
    assert rejected(sql).reason == "unknown_table"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM duckdb_tables()",
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "SELECT * FROM read_parquet('x.parquet')",
        "SELECT * FROM read_json_auto('x.json')",
        "SELECT * FROM glob('*')",
        "SELECT * FROM query('select 1')",
        "SELECT * FROM query_table('course')",
        "SELECT * FROM pragma_database_size()",
        "SELECT * FROM sqlite_scan('a', 'b')",
        "SELECT * FROM postgres_scan('a', 'b', 'c')",
        "SELECT current_setting('x')",
        "SELECT getenv('HOME')",
        "SELECT read_text('/etc/passwd')",
        "SELECT * FROM course WHERE shortname IN (SELECT content FROM read_text('/etc/passwd'))",
        "SELECT count(*) FROM duckdb_settings()",
        "SELECT course_id FROM course UNION SELECT 1 FROM read_csv_auto('x')",
    ],
)
def test_rejects_dangerous_functions(sql):
    assert rejected(sql).reason == "forbidden_function"


def test_parse_error_includes_parser_message():
    err = rejected("SELECT FROM WHERE (")
    assert err.reason == "parse_error"
    assert str(err)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Here you go:\n```sql\nSELECT 1\n```\nthanks", "SELECT 1"),
        ("```\nSELECT 2\n```", "SELECT 2"),
        ("Sure. The query is SELECT * FROM course", "SELECT * FROM course"),
        ("Answer: with x as (select 1) select * from x", "with x as (select 1) select * from x"),
        ("  SELECT 3  ", "SELECT 3"),
    ],
)
def test_extract_sql_from_model_output(text, expected):
    assert extract_sql_from_model_output(text) == expected
