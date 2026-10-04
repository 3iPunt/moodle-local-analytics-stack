"""Describe the exported schema for the API and for the model prompt."""

from __future__ import annotations

from typing import Any

import duckdb

BASE_SCHEMA = "base"

# Model-facing tables in prompt order, with the column used to filter by course.
TABLES = (
    "course",
    "participant",
    "daily_activity",
    "activity",
    "completion",
    "course_completion",
    "grade_item",
    "grade",
    "assignment_submission",
)
QUERY_TABLES: dict[str, str | None] = {name: "course_id" for name in TABLES}
TABLE_ORDER = (*TABLES, "export_meta")


def _order(name: str) -> tuple[int, str]:
    return (TABLE_ORDER.index(name) if name in TABLE_ORDER else len(TABLE_ORDER), name)


def describe_schema(conn: duckdb.DuckDBPyConnection, schema: str = BASE_SCHEMA) -> list[dict[str, Any]]:
    """Tables of ``schema`` with column types and comments."""
    rows = conn.execute(
        """
        SELECT t.table_name, coalesce(t.comment, ''), c.column_name, c.data_type, coalesce(c.comment, '')
        FROM duckdb_tables() AS t
        JOIN duckdb_columns() AS c USING (database_name, schema_name, table_name)
        WHERE t.schema_name = ? AND t.database_name = current_database() AND NOT t.temporary
        ORDER BY t.table_name, c.column_index
        """,
        [schema],
    ).fetchall()
    tables: dict[str, dict[str, Any]] = {}
    for table, table_comment, column, data_type, column_comment in rows:
        entry = tables.setdefault(table, {"name": table, "comment": table_comment, "columns": []})
        entry["columns"].append({"name": column, "type": data_type, "comment": column_comment})
    return [tables[name] for name in sorted(tables, key=_order)]


def _flat(text: str) -> str:
    return " ".join(text.split())


def schema_as_prompt_text(tables: list[dict[str, Any]]) -> str:
    """Render ``describe_schema`` output as commented CREATE TABLE statements."""
    blocks = []
    for table in tables:
        lines = [f"-- {_flat(table['comment'])}"] if table["comment"] else []
        lines.append(f"CREATE TABLE {table['name']} (")
        last = len(table["columns"]) - 1
        for i, column in enumerate(table["columns"]):
            sep = "," if i < last else ""
            note = f" -- {_flat(column['comment'])}" if column["comment"] else ""
            lines.append(f"    {column['name']} {column['type']}{sep}{note}")
        lines.append(");")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
