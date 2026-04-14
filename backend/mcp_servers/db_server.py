"""
Tools:
  - list_tables:          List all tables in the database.
  - describe_table:       Get column names, types, primary/foreign keys, and geometry SRIDs for a table.
  - get_schema_overview:  Full schema overview — all tables with columns, PKs, FKs, and spatial metadata.
  - explain_query:        Validate a SELECT query with EXPLAIN (no data returned). Use before query_database.
  - query_database:       Execute a read-only SELECT query.
"""

import json
import re
from typing import Any

from fastmcp import FastMCP
from db import get_connection, query


# Create the FastMCP server based on the FastMCP V2 framework.
mcp = FastMCP("db_fast_server")

_ALLOWED_SCHEMA_TABLES: dict[str, frozenset[str]] = {
    "kulturmiljoer": frozenset({
        "kommunenummer",
        "kulturmiljo",
        "kulturmiljogrense",
        "kulturmiljo_kommune",
        "vernetype",
    }),
    "public": frozenset({"norges_verdensarv", "points_of_interest"}),
}
_ALLOWED_SCHEMAS = frozenset(_ALLOWED_SCHEMA_TABLES)
_QUERY_ROW_LIMIT = 200
_QUERY_TIMEOUT_MS = 15_000
_ALLOWED_LEADING_TOKENS = frozenset({"SELECT", "WITH"})
_BLOCKED_SQL_TOKENS = frozenset({
    "ALTER",
    "BEGIN",
    "CALL",
    "CHECKPOINT",
    "CLUSTER",
    "COMMENT",
    "COMMIT",
    "COPY",
    "CREATE",
    "DEALLOCATE",
    "DELETE",
    "DISCARD",
    "DO",
    "DROP",
    "EXECUTE",
    "GRANT",
    "INSERT",
    "INTO",
    "LISTEN",
    "LOCK",
    "MERGE",
    "NOTIFY",
    "PREPARE",
    "REFRESH",
    "REINDEX",
    "RELEASE",
    "RESET",
    "REVOKE",
    "ROLLBACK",
    "SAVEPOINT",
    "SET",
    "SHOW",
    "TRUNCATE",
    "UNLISTEN",
    "UPDATE",
    "VACUUM",
})
_DOLLAR_QUOTE_RE = re.compile(r"\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$")
_READ_LOCK_CLAUSE_RE = re.compile(
    r"\bFOR\s+(?:NO\s+KEY\s+UPDATE|UPDATE|KEY\s+SHARE|SHARE)\b",
    re.IGNORECASE,
)


def _json_error(message: str) -> str:
    return json.dumps({"error": message})


def _schema_allowed(schema: str) -> bool:
    return schema in _ALLOWED_SCHEMAS


def _allowed_tables(schema: str) -> frozenset[str]:
    return _ALLOWED_SCHEMA_TABLES.get(schema, frozenset())


def _table_allowed(schema: str, table: str) -> bool:
    if not _schema_allowed(schema):
        return False
    return table in _allowed_tables(schema)


def _schema_error() -> str:
    return _json_error("Requested schema is not available through this tool.")


def _table_error(schema: str, table: str) -> str:
    return _json_error(f"Table {schema}.{table} is not available through this tool.")


def _not_found_error(schema: str, table: str) -> str:
    return _json_error(f"Table {schema}.{table} was not found or is not accessible.")


def _skip_single_quoted_literal(sql: str, start: int) -> int:
    i = start + 1
    while i < len(sql):
        if sql[i] == "'":
            if i + 1 < len(sql) and sql[i + 1] == "'":
                i += 2
                continue
            return i + 1
        i += 1
    return len(sql)


def _skip_double_quoted_identifier(sql: str, start: int) -> int:
    i = start + 1
    while i < len(sql):
        if sql[i] == '"':
            if i + 1 < len(sql) and sql[i + 1] == '"':
                i += 2
                continue
            return i + 1
        i += 1
    return len(sql)


def _skip_line_comment(sql: str, start: int) -> int:
    i = start + 2
    while i < len(sql) and sql[i] not in "\r\n":
        i += 1
    return i


def _skip_block_comment(sql: str, start: int) -> int:
    depth = 1
    i = start + 2
    while i < len(sql):
        if sql.startswith("/*", i):
            depth += 1
            i += 2
            continue
        if sql.startswith("*/", i):
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    return len(sql)


def _skip_dollar_quoted_literal(sql: str, start: int) -> int | None:
    match = _DOLLAR_QUOTE_RE.match(sql, start)
    if not match:
        return None

    tag = match.group(0)
    end = sql.find(tag, match.end())
    if end == -1:
        return len(sql)
    return end + len(tag)


def _normalize_sql(sql: str) -> tuple[str | None, str | None]:
    if not sql or not sql.strip():
        return None, "SQL query is required."

    tokens: list[str] = []
    trailing_semicolon_index: int | None = None
    i = 0

    while i < len(sql):
        if sql.startswith("--", i):
            i = _skip_line_comment(sql, i)
            continue
        if sql.startswith("/*", i):
            i = _skip_block_comment(sql, i)
            continue

        if trailing_semicolon_index is not None:
            if sql[i].isspace():
                i += 1
                continue
            return None, "Only a single SQL statement is allowed."

        ch = sql[i]
        if ch == "'":
            i = _skip_single_quoted_literal(sql, i)
            continue
        if ch == '"':
            i = _skip_double_quoted_identifier(sql, i)
            continue
        if ch == "$":
            dollar_end = _skip_dollar_quoted_literal(sql, i)
            if dollar_end is not None:
                i = dollar_end
                continue
        if ch == ";":
            trailing_semicolon_index = i
            i += 1
            continue
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < len(sql) and (sql[i].isalnum() or sql[i] in {"_", "$"}):
                i += 1
            tokens.append(sql[start:i].upper())
            continue
        i += 1

    normalized = sql[:trailing_semicolon_index].strip() if trailing_semicolon_index is not None else sql.strip()
    if not normalized:
        return None, "SQL query is required."
    if not tokens:
        return None, "Unable to parse the SQL query."
    if tokens[0] not in _ALLOWED_LEADING_TOKENS:
        return None, "Only SELECT queries are allowed. WITH ... SELECT is also supported."

    blocked = next((token for token in tokens if token in _BLOCKED_SQL_TOKENS), None)
    if blocked:
        return None, f"Only read-only SELECT queries are allowed. Found disallowed keyword: {blocked}."

    visible_sql = _sql_visible_text(normalized)
    if _READ_LOCK_CLAUSE_RE.search(visible_sql):
        return None, "SELECT ... FOR UPDATE/SHARE queries are not allowed."

    return normalized, None


async def _run_query(sql: str) -> list[dict[str, Any]]:
    async with get_connection() as conn:
        async with conn.transaction(force_rollback=True):
            async with conn.cursor() as cur:
                await cur.execute("SET TRANSACTION READ ONLY")
                timeout_value = f"{_QUERY_TIMEOUT_MS}ms"
                await cur.execute(f"SET LOCAL statement_timeout = '{timeout_value}'")
                await cur.execute(f"SET LOCAL lock_timeout = '{timeout_value}'")
                await cur.execute(sql)
                if cur.description is None:
                    return []
                return await cur.fetchall()


def _sql_visible_text(sql: str) -> str:
    parts: list[str] = []
    i = 0

    while i < len(sql):
        if sql.startswith("--", i):
            i = _skip_line_comment(sql, i)
            parts.append(" ")
            continue
        if sql.startswith("/*", i):
            i = _skip_block_comment(sql, i)
            parts.append(" ")
            continue

        ch = sql[i]
        if ch == "'":
            i = _skip_single_quoted_literal(sql, i)
            parts.append(" ")
            continue
        if ch == '"':
            i = _skip_double_quoted_identifier(sql, i)
            parts.append(" ")
            continue
        if ch == "$":
            dollar_end = _skip_dollar_quoted_literal(sql, i)
            if dollar_end is not None:
                i = dollar_end
                parts.append(" ")
                continue

        parts.append(ch)
        i += 1

    return "".join(parts)


def _extract_relations(node: Any, relations: set[tuple[str, str]]) -> None:
    if isinstance(node, dict):
        schema = node.get("Schema")
        relation_name = node.get("Relation Name")
        if schema and relation_name:
            relations.add((str(schema), str(relation_name)))
        for value in node.values():
            _extract_relations(value, relations)
        return

    if isinstance(node, list):
        for item in node:
            _extract_relations(item, relations)


def _error_hint(error_msg: str) -> str:
    hint = ""
    lc = error_msg.lower()
    if "nested" in lc and "aggregate" in lc:
        hint = (
            " Use a CTE (WITH clause) or sub-query: first apply the inner aggregate, "
            "then apply the outer function on the result."
        )
    elif "srid" in lc or "mixed" in lc:
        hint = (
            " Ensure spatial predicates use compatible SRIDs and apply ST_Transform as needed."
        )
    elif "column" in lc and "does not exist" in lc:
        hint = (
            " Call describe_table or get_schema_overview to confirm the exact column names."
        )
    return hint


async def _validate_query_sql(sql: str) -> tuple[str | None, str | None]:
    normalized_sql, parse_error = _normalize_sql(sql)
    if parse_error:
        return None, parse_error

    try:
        plan_rows = await _run_query(f"EXPLAIN (VERBOSE, FORMAT JSON) {normalized_sql}")
    except Exception as exc:
        error_msg = str(exc)
        return None, f"Query validation failed: {error_msg}{_error_hint(error_msg)}"

    if not plan_rows:
        return None, "Query validation failed: EXPLAIN returned no plan."

    raw_plan = next(iter(plan_rows[0].values()), None)
    try:
        plan_doc = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
    except json.JSONDecodeError:
        return None, "Query validation failed: unexpected EXPLAIN output."

    referenced_relations: set[tuple[str, str]] = set()
    _extract_relations(plan_doc, referenced_relations)

    if not referenced_relations:
        return None, "Query must read from at least one approved Atlas table."

    disallowed_relations = [
        (schema, table)
        for schema, table in referenced_relations
        if (not _schema_allowed(schema)) or (not _table_allowed(schema, table))
    ]
    if disallowed_relations:
        return None, "Query references one or more tables that are not available through this tool."

    return normalized_sql, None


def _limit_query(sql: str) -> str:
    return (
        "SELECT * "
        f"FROM ({sql}) AS atlas_query "
        f"LIMIT {_QUERY_ROW_LIMIT}"
    )


@mcp.tool
async def list_tables() -> str:
    """
    List the database tables that this tool is allowed to expose.
    Call this first to discover what data is available through the server.
    """
    try:
        rows = await query("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY(%s)
              AND table_name NOT IN ('spatial_ref_sys', 'geometry_columns', 'geography_columns')
            ORDER BY table_schema, table_name
        """, (sorted(_ALLOWED_SCHEMAS),))
        tables = [
            {"schema": r["table_schema"], "table": r["table_name"]}
            for r in rows
            if _table_allowed(r["table_schema"], r["table_name"])
        ]
        return json.dumps(tables, indent=2)
    except Exception as exc:
        return _json_error(f"Could not list tables: {exc}")


@mcp.tool
async def describe_table(schema: str, table: str) -> str:
    """
    Get the structure of one approved table, including columns, keys, and spatial metadata.

    Args:
        schema: The schema name.
        table:  The table name.
    """
    if not _schema_allowed(schema):
        return _schema_error()
    if not _table_allowed(schema, table):
        return _table_error(schema, table)

    try:
        # Columns with nullable info
        col_rows = await query("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
        """, (schema, table))
        if not col_rows:
            return _not_found_error(schema, table)

        # Primary key columns
        pk_rows = await query("""
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s AND tc.table_name = %s
            ORDER BY kcu.ordinal_position
        """, (schema, table))
        pk_columns = {r["column_name"] for r in pk_rows}

        # Foreign key relationships
        fk_rows = await query("""
            SELECT kcu.column_name,
                   ccu.table_schema AS ref_schema,
                   ccu.table_name   AS ref_table,
                   ccu.column_name  AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s AND tc.table_name = %s
        """, (schema, table))
        fk_map = {
            r["column_name"]: f"{r['ref_schema']}.{r['ref_table']}.{r['ref_column']}"
            for r in fk_rows
            if _table_allowed(r["ref_schema"], r["ref_table"])
        }

        # Geometry column SRIDs (PostGIS)
        geom_rows = await query("""
            SELECT f_geometry_column, srid, type
            FROM geometry_columns
            WHERE f_table_schema = %s AND f_table_name = %s
        """, (schema, table))
        geom_map = {
            r["f_geometry_column"]: {"srid": r["srid"], "type": r["type"]}
            for r in geom_rows
        }

        columns = []
        for r in col_rows:
            col: dict = {
                "column": r["column_name"],
                "type": r["data_type"],
                "nullable": r["is_nullable"],
            }
            if r["column_name"] in pk_columns:
                col["primary_key"] = True
            if r["column_name"] in fk_map:
                col["foreign_key_references"] = fk_map[r["column_name"]]
            if r["column_name"] in geom_map:
                col["geometry_srid"] = geom_map[r["column_name"]]["srid"]
                col["geometry_type"] = geom_map[r["column_name"]]["type"]
            columns.append(col)

        return json.dumps({"schema": schema, "table": table, "columns": columns}, indent=2)
    except Exception as exc:
        return _json_error(f"Could not describe table {schema}.{table}: {exc}")


@mcp.tool
async def get_schema_overview(schema: str) -> str:
    """
    Return metadata for every approved table in a schema.

    Args:
        schema: The schema name.
    """
    if not _schema_allowed(schema):
        return _schema_error()

    try:
        # All columns for schema
        col_rows = await query("""
            SELECT table_name, column_name, data_type, is_nullable, ordinal_position
            FROM information_schema.columns
            WHERE table_schema = %s
            ORDER BY table_name, ordinal_position
        """, (schema,))
        col_rows = [r for r in col_rows if _table_allowed(schema, r["table_name"])]
        if not col_rows:
            return _json_error(f"No approved tables were found in schema {schema}.")

        # All PKs within schema
        pk_rows = await query("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = %s
        """, (schema,))
        pks: dict[str, set] = {}
        for r in pk_rows:
            if _table_allowed(schema, r["table_name"]):
                pks.setdefault(r["table_name"], set()).add(r["column_name"])

        # All FKs originating from this schema
        fk_rows = await query("""
            SELECT tc.table_name, kcu.column_name,
                   ccu.table_schema AS ref_schema,
                   ccu.table_name   AS ref_table,
                   ccu.column_name  AS ref_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = %s
        """, (schema,))
        fks: dict[str, dict] = {}
        for r in fk_rows:
            if _table_allowed(schema, r["table_name"]):
                if _table_allowed(r["ref_schema"], r["ref_table"]):
                    fks.setdefault(r["table_name"], {})[r["column_name"]] = (
                        f"{r['ref_schema']}.{r['ref_table']}.{r['ref_column']}"
                    )

        # All geometry columns with SRID
        geom_rows = await query("""
            SELECT f_table_name, f_geometry_column, srid, type
            FROM geometry_columns
            WHERE f_table_schema = %s
        """, (schema,))
        geoms: dict[str, dict] = {}
        for r in geom_rows:
            if _table_allowed(schema, r["f_table_name"]):
                geoms.setdefault(r["f_table_name"], {})[r["f_geometry_column"]] = {
                    "srid": r["srid"],
                    "type": r["type"],
                }

        # Assemble per-table output
        tables: dict[str, list] = {}
        for r in col_rows:
            tname = r["table_name"]
            col: dict = {
                "column": r["column_name"],
                "type": r["data_type"],
            }
            if r["column_name"] in pks.get(tname, set()):
                col["primary_key"] = True
            if r["column_name"] in fks.get(tname, {}):
                col["foreign_key_references"] = fks[tname][r["column_name"]]
            if r["column_name"] in geoms.get(tname, {}):
                col["geometry_srid"] = geoms[tname][r["column_name"]]["srid"]
                col["geometry_type"] = geoms[tname][r["column_name"]]["type"]
            tables.setdefault(tname, []).append(col)

        result = {"schema": schema, "tables": {t: cols for t, cols in tables.items()}}
        return json.dumps(result, indent=2)
    except Exception as exc:
        return _json_error(f"Could not inspect schema {schema}: {exc}")


@mcp.tool
async def explain_query(sql: str) -> str:
    """
    Validate a read-only query by running EXPLAIN without fetching data rows.
    The query must reference only approved Atlas tables.

    Args:
        sql: A single read-only SELECT query. WITH ... SELECT is supported.
    """
    normalized_sql, validation_error = await _validate_query_sql(sql)
    if validation_error:
        return json.dumps({"valid": False, "error": validation_error})

    try:
        rows = await _run_query(f"EXPLAIN {normalized_sql}")
        plan = [list(r.values())[0] for r in rows]
        return json.dumps({"valid": True, "plan": plan})
    except Exception as exc:
        error_msg = str(exc)
        return json.dumps({"valid": False, "error": f"{error_msg}{_error_hint(error_msg)}"})


@mcp.tool
async def query_database(sql: str) -> str:
    """
    Execute a read-only SELECT query against the database.
    Returns the results as a JSON array. Only single-statement SELECT / WITH ... SELECT
    queries against approved Atlas data tables are permitted. Results are capped to
    200 rows and run with a statement timeout.

    Call list_tables first to discover which tables are available, then
    describe_table to see the exact column names before writing SQL.

    Args:
        sql: A single read-only SELECT query. WITH ... SELECT is supported.
    """
    normalized_sql, validation_error = await _validate_query_sql(sql)
    if validation_error:
        return _json_error(validation_error)

    try:
        rows = await _run_query(_limit_query(normalized_sql))
        return json.dumps(rows, indent=2, default=str)
    except Exception as exc:
        error_msg = str(exc)
        return _json_error(f"Query execution failed: {error_msg}{_error_hint(error_msg)}")

db_app = mcp.http_app(path="/mcp")
