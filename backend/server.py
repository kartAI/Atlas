"""
Main Starlette application.

Mounts three MCP servers alongside the existing REST API:

  /mcp/db/mcp    — Database tools  (list_tables, describe_table, query_database)
  /mcp/geo/mcp   — Geo tools       (list_kommuner, list_vernetyper, buffer_search)
  /mcp/docs/mcp  — Document tools  (list_documents, fetch_document)
  /api/chat      — Orchestrator chat endpoint (unchanged)
  /api/history   — Session history  (unchanged)
  /api/documents — Azure document list (unchanged)

The orchestrator in session_manager.py points the Copilot client at
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import ALLOWED_ORIGINS, DEMO_MODE, HOST, PORT, list_documents
from copilot import CopilotClient
from session_manager import SessionManager
from db import connect_db, disconnect_db, query

# Import the three MCP ASGI apps
from mcp_servers.db_server import db_app
from mcp_servers.geo_server import geo_app
from mcp_servers.docs_server import docs_app

# Copilot client and session manager initialization.
client = CopilotClient()
manager = SessionManager(client)



# Lifespan, start and stop in the right order.
@asynccontextmanager
async def lifespan(app):
    async with db_app.lifespan(app):
        async with geo_app.lifespan(app):
            async with docs_app.lifespan(app):
                await client.start()
                await connect_db()
                yield
                await client.stop()
                await disconnect_db()

# REST endpoint handlers
async def chat(request: Request):
    data = await request.json()
    message = data.get("message")
    if not message:
        return JSONResponse({"error": "'message' is required."}, status_code=400)
    session_id = data.get("session_id")
    session_id, session = await manager.get_or_create(session_id)
    reply = await manager.send_message(session_id, message)
    return JSONResponse({"reply": reply, "session_id": session_id})


async def get_documents(request: Request):
    docs = list_documents()
    return JSONResponse({"documents": docs})


async def get_history(request: Request):
    session_id = request.path_params["session_id"]
    history = manager.get_history(session_id)
    return JSONResponse({"history": history})


async def test_db(request: Request):
    if not DEMO_MODE:
        return JSONResponse({"error": "Only available in demo mode."})
    result = await query("SELECT * FROM kulturmiljoer.kommunenummer LIMIT 5")
    return JSONResponse({"data": result})



# Assemble the Starlette application
app = Starlette(
    routes=[
        # MCP servers — each accessible at /mcp/<name>/mcp
        Mount("/mcp/db",   app=db_app),
        Mount("/mcp/geo",  app=geo_app),
        Mount("/mcp/docs", app=docs_app),

        # Existing REST API
        Route("/api/chat",                  endpoint=chat,          methods=["POST"]),
        Route("/api/documents",             endpoint=get_documents, methods=["GET"]),
        Route("/api/history/{session_id}",  endpoint=get_history,   methods=["GET"]),
        Route("/api/test-db",               endpoint=test_db,       methods=["GET"]),
    ],
    middleware=[
        Middleware(
            CORSMiddleware,
            allow_origins=ALLOWED_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ],
    lifespan=lifespan,
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=HOST, port=PORT, reload=True)