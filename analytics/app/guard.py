"""SQL guard for model-generated queries.

The guard is the first of two layers. It parses the model's SQL with sqlglot
(DuckDB dialect) and only lets through a single read-only query (SELECT, WITH,
or a set operation of selects) that references the allowed view names, CTEs
defined in scope, and a small allowlist of harmless table functions.

It does not inspect string literals for file paths or URLs: that would be
brittle. File and network access is instead blocked by a function denylist
here and, as the second layer, by the DuckDB connection settings
(``enable_external_access=False``, ``lock_configuration=True``, read-only file).
"""

from __future__ import annotations

import logging
import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, SqlglotError, TokenError
from sqlglot.tokens import TokenType

logging.getLogger("sqlglot").setLevel(logging.ERROR)

DIALECT = "duckdb"

DENIED_FUNCTIONS = frozenset(
    {
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_json_objects_auto",
        "read_ndjson",
        "read_ndjson_auto",
        "read_ndjson_objects",
        "read_text",
        "read_blob",
        "read_xlsx",
        "glob",
        "parquet_scan",
        "parquet_metadata",
        "parquet_schema",
        "parquet_file_metadata",
        "parquet_kv_metadata",
        "csv_scan",
        "json_scan",
        "sqlite_scan",
        "sqlite_attach",
        "mysql_scan",
        "mysql_query",
        "postgres_scan",
        "postgres_scan_pushdown",
        "postgres_query",
        "postgres_attach",
        "iceberg_scan",
        "iceberg_metadata",
        "iceberg_snapshots",
        "delta_scan",
        "current_setting",
        "getenv",
        "query",
        "query_table",
        "sniff_csv",
        "load_aws_credentials",
        "which_secret",
        "checkpoint",
        "force_checkpoint",
        "test_all_types",
    }
)
DENIED_PREFIXES = ("duckdb_", "pragma_", "sqlite_", "mysql_", "postgres_", "iceberg_", "delta_", "read_")

ALLOWED_TABLE_FUNCTIONS = frozenset({"range", "generate_series", "unnest"})

SYSTEM_SCHEMAS = frozenset({"information_schema", "pg_catalog"})

ALLOWED_ROOTS = (exp.Select, exp.SetOperation, exp.Subquery)

FORBIDDEN_NODES = tuple(
    getattr(exp, name)
    for name in (
        "Insert",
        "Update",
        "Delete",
        "Merge",
        "Create",
        "Drop",
        "Alter",
        "Command",
        "Copy",
        "Attach",
        "Detach",
        "Pragma",
        "Set",
        "Use",
        "Describe",
        "Summarize",
        "Show",
        "Install",
        "Transaction",
        "Commit",
        "Rollback",
        "LoadData",
        "Export",
    )
    if hasattr(exp, name)
)

_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_-]*)[ \t]*\n?(.*?)```", re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"```[ \t]*[A-Za-z0-9_-]*[ \t]*\n?(.*)$", re.DOTALL)
_SQL_START_RE = re.compile(r"\b(WITH|SELECT)\b", re.IGNORECASE)


class GuardError(ValueError):
    """Rejected query. ``reason`` is a stable code, ``message`` is for the model."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


def extract_sql_from_model_output(text: str) -> str:
    """Pull the SQL out of a free-form model answer."""
    blocks = _FENCE_RE.findall(text or "")
    for lang, body in blocks:
        if lang.lower() == "sql":
            return body.strip()
    if blocks:
        return blocks[0][1].strip()
    match = _SQL_START_RE.search(text or "")
    if match:
        return text[match.start():].strip()
    return (text or "").strip()


def _strip_fences(sql: str) -> str:
    text = sql.strip()
    if "```" in text:
        blocks = _FENCE_RE.findall(text)
        if blocks:
            sql_blocks = [body for lang, body in blocks if lang.lower() == "sql"]
            text = (sql_blocks or [blocks[0][1]])[0]
        else:
            match = _OPEN_FENCE_RE.search(text)
            text = match.group(1) if match else text.replace("```", "")
    text = text.strip()
    if text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def _func_names(node: exp.Expression) -> set[str]:
    names = set()
    if isinstance(node, exp.Anonymous):
        names.add(node.name.lower())
    else:
        names.add(node.sql_name().lower())
        head = node.sql(dialect=DIALECT).split("(", 1)[0].strip().strip('"').lower()
        if head:
            names.add(head)
    return names


def _is_denied(names: set[str]) -> bool:
    return any(n in DENIED_FUNCTIONS or n.startswith(DENIED_PREFIXES) for n in names)


def _ctes_in_scope(table: exp.Table) -> set[str]:
    names: set[str] = set()
    node = table.parent
    while node is not None:
        with_ = node.args.get("with_") or node.args.get("with")
        if isinstance(with_, exp.With):
            names.update(cte.alias_or_name.lower() for cte in with_.expressions)
        node = node.parent
    return names


def _check_table(table: exp.Table, allowed: set[str], allowed_list: str) -> None:
    source = table.this
    if isinstance(source, exp.Func):
        names = _func_names(source)
        if _is_denied(names) or not names & ALLOWED_TABLE_FUNCTIONS:
            name = sorted(names)[0]
            raise GuardError(
                "forbidden_function",
                f"table function '{name}' is not allowed; query the views directly: {allowed_list}",
            )
        return

    name = table.name
    schema = table.text("db").lower()
    catalog = table.text("catalog").lower()
    if schema or catalog:
        qualified = ".".join(p for p in (catalog, schema, name) if p)
        if schema in SYSTEM_SCHEMAS or catalog in SYSTEM_SCHEMAS:
            raise GuardError(
                "system_catalog",
                f"system catalog '{qualified}' is not available; use one of: {allowed_list}",
            )
        raise GuardError(
            "qualified_table",
            f"qualified name '{qualified}' is not allowed; reference the view by its bare name, one of: {allowed_list}",
        )

    lowered = name.lower()
    if lowered in allowed or lowered in _ctes_in_scope(table):
        return
    raise GuardError(
        "unknown_table",
        f"table '{name}' is not available; use one of: {allowed_list}",
    )


def _parse_single(text: str) -> exp.Expression:
    try:
        tokens = sqlglot.tokenize(text, read=DIALECT)
    except TokenError as err:
        raise GuardError("parse_error", f"could not parse SQL: {err}") from err
    if any(t.token_type == TokenType.SEMICOLON for t in tokens):
        raise GuardError("multiple_statements", "send exactly one SELECT statement, without ';' separators")
    try:
        statements = [s for s in sqlglot.parse(text, read=DIALECT) if s is not None]
    except ParseError as err:
        raise GuardError("parse_error", f"could not parse SQL: {err}") from err
    if len(statements) != 1:
        raise GuardError("multiple_statements", "send exactly one SELECT statement")
    return statements[0]


def validate_sql(sql: str, allowed_tables: set[str], max_rows: int) -> str:
    """Validate model SQL and return the capped query to execute."""
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or max_rows < 1:
        raise ValueError("max_rows must be a positive integer")
    allowed = {t.lower() for t in allowed_tables}
    allowed_list = ", ".join(sorted(allowed))

    text = _strip_fences(sql or "")
    if not text:
        raise GuardError("empty", "the query is empty; send one SELECT statement")

    try:
        statement = _parse_single(text)

        if not isinstance(statement, ALLOWED_ROOTS) or isinstance(statement, FORBIDDEN_NODES):
            kind = statement.key.upper()
            raise GuardError("not_select", f"only SELECT queries are allowed, got {kind}")

        for node in statement.walk():
            if isinstance(node, FORBIDDEN_NODES):
                raise GuardError("not_select", f"only SELECT queries are allowed, found {node.key.upper()}")
            if isinstance(node, exp.Select) and node.args.get("into") is not None:
                raise GuardError("select_into", "SELECT ... INTO is not allowed; return the rows instead")
            if isinstance(node, exp.Table):
                _check_table(node, allowed, allowed_list)
            elif isinstance(node, exp.Func) and _is_denied(_func_names(node)):
                name = sorted(_func_names(node))[0]
                raise GuardError("forbidden_function", f"function '{name}' is not allowed")

        inner = statement.sql(dialect=DIALECT)
    except (RecursionError, SqlglotError) as err:
        raise GuardError("parse_error", "the query is too complex or nested to analyse") from err

    return f"SELECT * FROM ({inner}) AS q LIMIT {max_rows}"
