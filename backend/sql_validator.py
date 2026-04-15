"""
SQL safety validation using SQLGlot (AST-based) before agent-generated queries
are executed against the database.

Defence layers
--------------
1. SQLGlot parses the SQL into an AST so we can inspect structure, not just text.
2. We reject anything that is not a single, plain SELECT statement.
3. We walk the AST to block DDL / DML hidden inside CTEs or subqueries.
4. We extract every table reference and compare against an explicit allowlist.

The caller (db_server.query_database) also wraps execution in a PostgreSQL
READ ONLY transaction as a final backstop.
"""

from __future__ import annotations

import os
import sqlglot
import sqlglot.expressions as exp

# ---------------------------------------------------------------------------
# Allowlist: loaded at startup from the SQL_ALLOWED_SCHEMAS environment variable
# so schema names are never committed to the repository.
#
#
# Each listed schema allows ALL tables within it ("schema.*").
# The allowlist is a defence-in-depth measure. The primary safety net is the
# PostgreSQL READ ONLY transaction and the DB role's own GRANT permissions.
# ---------------------------------------------------------------------------
def _load_allowed_schemas() -> set[tuple[str, str]]:
    raw = os.getenv("SQL_ALLOWED_SCHEMAS", "")
    schemas = {s.strip().lower() for s in raw.split(",") if s.strip()}
    return {(schema, "*") for schema in schemas}

ALLOWED_TABLES: set[tuple[str, str]] = _load_allowed_schemas()

_BLOCKED_FUNCTIONS = {"pg_sleep","pg_sleep_for","pg_sleep_until"}

def _check_functions(stmt: exp.Select) -> None:
    for node in stmt.find_all(exp.Func):
        if node.sql_name().lower() in _BLOCKED_FUNCTIONS:
            raise SQLValidationError(f"Function '{node.sql_name()}' is not permitted.")
        
# AST node types that indicate write / structural operations
_FORBIDDEN_EXPRESSION_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Command,      # catches PostgreSQL COPY, VACUUM, SET, etc.
)

def _schema_allowed(schema: str, table: str) -> bool:
    """Return True if (schema, table) matches any entry in ALLOWED_TABLES."""
    return (
        (schema, table) in ALLOWED_TABLES
        or (schema, "*") in ALLOWED_TABLES
        or ("*", "*") in ALLOWED_TABLES
    )


class SQLValidationError(ValueError):
    """Raised when a query fails the safety checks."""


def validate_select_query(sql: str) -> str:
    """
    Parse *sql* with SQLGlot (PostgreSQL dialect) and verify it is a safe,
    read-only SELECT statement.

    Returns the normalised SQL string on success.
    Raises SQLValidationError with a descriptive message on failure.
    """
    sql = sql.strip()
    if not sql:
        raise SQLValidationError("Empty query.")

    # --- 1. Parse -------------------------------------------------------
    try:
        statements = sqlglot.parse(sql, dialect="postgres", error_level=sqlglot.ErrorLevel.RAISE)
    except sqlglot.errors.ParseError as exc:
        raise SQLValidationError(f"SQL syntax error: {exc}") from exc

    # --- 2. Single statement only ---------------------------------------
    if len(statements) != 1:
        raise SQLValidationError(
            f"Exactly one SELECT statement is allowed; got {len(statements)}."
        )

    stmt = statements[0]

    # --- 3. Top-level must be SELECT ------------------------------------
    if not isinstance(stmt, exp.Select):
        raise SQLValidationError(
            f"Only SELECT statements are allowed; got {type(stmt).__name__}."
        )

    # --- 4. No DDL / DML anywhere in the AST (catches CTE tricks) -------
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN_EXPRESSION_TYPES):
            raise SQLValidationError(
                f"Forbidden operation detected inside query: {type(node).__name__}."
            )

    # --- 5. Function allowlist check ---------------------------------------
    _check_functions(stmt)

    # --- 6. Table allowlist check ---------------------------------------
    _check_table_allowlist(stmt)

    # Return the canonical, dialect-normalised SQL
    return stmt.sql(dialect="postgres")


def _check_table_allowlist(stmt: exp.Select) -> None:
    """Walk all Table references and ensure every one matches ALLOWED_TABLES."""
    for table_node in stmt.find_all(exp.Table):
        db_arg = table_node.args.get("db")
        schema = (db_arg.name if db_arg else "public").lower()
        name = (table_node.name or "").lower()
        if not name:
            continue
        if not _schema_allowed(schema, name):
            raise SQLValidationError(
                f'Schema "{schema}" is not in the allowed list. '
                f'Add ("{schema}", "*") to ALLOWED_TABLES in sql_validator.py.'
            )
