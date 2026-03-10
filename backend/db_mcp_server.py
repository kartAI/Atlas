"""
gruppe8-db-mcp: MCP server for the gruppe8_2026 PostgreSQL database.

Exposes read-only tools so the Copilot agent can explore and query the database
autonomously via the Model Context Protocol (MCP).

Tools:
  - list_tables:     List all tables in the database.
  - describe_table:  Get column names and types for a given table.
  - query_database:  Execute a read-only SELECT query and return results as JSON.
"""

import json
import os

import asyncpg
import uvicorn
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("MCP_PORT", "8002"))

mcp = FastMCP("gruppe8-db")


async def get_connection() -> asyncpg.Connection:
    """Open a new SSL-secured connection to the Azure PostgreSQL database."""
    return await asyncpg.connect(DATABASE_URL, ssl="require")


@mcp.tool()
async def list_tables() -> str:
    """
    List all available tables and their schemas in the gruppe8_2026 database.
    Call this first to discover what data is available.
    """
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
        """)
        tables = [{"schema": r["table_schema"], "table": r["table_name"]} for r in rows]
        return json.dumps(tables, indent=2)
    finally:
        await conn.close()


@mcp.tool()
async def describe_table(schema: str, table: str) -> str:
    """
    Get column names, data types, and nullability for a specific table.
    Use this before querying to understand the table structure.

    Args:
        schema: The schema name (e.g. 'kulturmiljoer' or 'public').
        table:  The table name (e.g. 'kulturmiljo').
    """
    conn = await get_connection()
    try:
        rows = await conn.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """, schema, table)
        columns = [
            {"column": r["column_name"], "type": r["data_type"], "nullable": r["is_nullable"]}
            for r in rows
        ]
        return json.dumps(columns, indent=2)
    finally:
        await conn.close()


@mcp.tool()
async def query_database(sql: str) -> str:
    """
    Execute a read-only SELECT query against the gruppe8_2026 database.
    Returns the results as a JSON array.

    Only SELECT statements are permitted.

    Args:
        sql: A valid PostgreSQL SELECT query.
    """
    if not sql.strip().upper().startswith("SELECT"):
        return json.dumps({"error": "Only SELECT queries are allowed."})
    conn = await get_connection()
    try:
        rows = await conn.fetch(sql)
        result = [dict(r) for r in rows]
        return json.dumps(result, indent=2, default=str)
    finally:
        await conn.close()


if __name__ == "__main__":
    app = Starlette(routes=[Mount("/", app=mcp.sse_app())])
    uvicorn.run(app, host="0.0.0.0", port=PORT)
