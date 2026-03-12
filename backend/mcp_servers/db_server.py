"""
Tools:
  - list_tables:    List all tables in the database.
  - describe_table: Get column names and types for a given table.
  - query_database: Execute a read-only SELECT query.
"""

import json

from fastmcp import FastMCP
from db import query


# Create the FastMCP server based on the FastMCP V2 framework.
mcp = FastMCP("db_fast_server")


@mcp.tool
async def list_tables() -> str:
    """
    List all available tables and their schemas in the database.
    Call this first to discover what data is available.
    """
    rows = await query("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name
    """)
    tables = [{"schema": r["table_schema"], "table": r["table_name"]} for r in rows]
    return json.dumps(tables, indent=2)


@mcp.tool
async def describe_table(schema: str, table: str) -> str:
    """
    Get column names, data types, and nullability for a specific table.
    Use this before querying to understand the table structure.

    Args:
        schema: The schema name (e.g. 'kulturmiljoer' or 'public').
        table:  The table name (e.g. 'kulturmiljo').
    """
    rows = await query("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
    """, (schema, table))
    columns = [
        {"column": r["column_name"], "type": r["data_type"], "nullable": r["is_nullable"]}
        for r in rows
    ]
    return json.dumps(columns, indent=2)


@mcp.tool
async def query_database(sql: str) -> str:
    """
    Execute a read-only SELECT query against the database.
    Returns the results as a JSON array. Only SELECT statements are permitted.

    Args:
        sql: A valid PostgreSQL SELECT query.
    """
    if not sql.strip().upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed."})
    rows = await query(sql)
    return json.dumps(rows, indent=2, default=str)

db_app = mcp.http_app(path="/mcp")