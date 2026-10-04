import duckdb
import pytest

from app.schema import describe_schema, schema_as_prompt_text


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("CREATE SCHEMA base")
    c.execute("CREATE TABLE base.zeta (id BIGINT, note VARCHAR)")
    c.execute("CREATE TABLE base.course (course_id BIGINT, shortname VARCHAR)")
    c.execute("CREATE TABLE main.ignored (x INTEGER)")
    c.execute("COMMENT ON TABLE base.course IS 'One row per course.'")
    c.execute("COMMENT ON COLUMN base.course.course_id IS 'Course id.\nPrimary key.'")
    c.execute("COMMENT ON COLUMN base.course.shortname IS 'Short code.'")
    yield c
    c.close()


def test_describe_schema_lists_base_tables_in_model_order(con):
    assert describe_schema(con) == [
        {
            "name": "course",
            "comment": "One row per course.",
            "columns": [
                {"name": "course_id", "type": "BIGINT", "comment": "Course id.\nPrimary key."},
                {"name": "shortname", "type": "VARCHAR", "comment": "Short code."},
            ],
        },
        {
            "name": "zeta",
            "comment": "",
            "columns": [
                {"name": "id", "type": "BIGINT", "comment": ""},
                {"name": "note", "type": "VARCHAR", "comment": ""},
            ],
        },
    ]


def test_schema_as_prompt_text_renders_ddl_with_inline_comments(con):
    text = schema_as_prompt_text(describe_schema(con))
    assert text.startswith("-- One row per course.\nCREATE TABLE course (\n")
    assert "    course_id BIGINT, -- Course id. Primary key.\n" in text
    assert "    shortname VARCHAR -- Short code.\n);" in text
    assert "CREATE TABLE zeta (\n    id BIGINT,\n    note VARCHAR\n);" in text
    assert "ignored" not in text
