"""
Main Starlette application.

Mounts MCP servers alongside the existing REST API:

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
from db import init_db_pool, close_pool, query

# Import the MCP ASGI apps
from mcp_servers.db_server import db_app
from mcp_servers.geo_server import geo_app
from mcp_servers.docs_server import docs_app
from mcp_servers.vector_server import vector_app
from mcp_servers.map_server import map_app

# Copilot client and session manager initialization.
client = CopilotClient()
manager = SessionManager(client)



# Lifespan, start and stop in the right order.
@asynccontextmanager
async def lifespan(app):
    async with db_app.lifespan(app):
        async with geo_app.lifespan(app):
            async with docs_app.lifespan(app):
                async with vector_app.lifespan(app):
                    async with map_app.lifespan(app):
                        await init_db_pool()
                        await client.start()
                        manager.start_cleanup_loop()
                        yield
                        manager.stop_cleanup_loop()
                        await client.stop()
                        await close_pool()


# REST endpoint handlers
async def chat(request: Request):
    data = await request.json()
    message = data.get("message")
    map_context = data.get("map_context")
    if not message:
        return JSONResponse({"error": "'message' is required."}, status_code=400)
    session_id = data.get("session_id")
    try:
        session_id, session = await manager.get_or_create(session_id)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=503)
    result = await manager.send_message(session_id, message, map_context=map_context)
    return JSONResponse({
        "reply": result["content"],
        "session_id": session_id,
        "map_actions": result["map_actions"],
    })


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


async def test_search(request: Request):
    """Quick REST endpoint to test document search without MCP protocol."""
    q = request.query_params.get("q", "")
    if not q:
        return JSONResponse({"error": "Bruk ?q=søkeord"}, status_code=400)
    from search_service import search_full_text, search_fuzzy, hybrid_search
    mode = request.query_params.get("mode", "fulltext")
    if mode == "fuzzy":
        results = await search_fuzzy(q)
    elif mode == "hybrid":
        results = await hybrid_search(q)
    else:
        results = await search_full_text(q)
    return JSONResponse({"query": q, "mode": mode, "count": len(results), "results": results})



# Assemble the Starlette application
app = Starlette(
    routes=[
        # MCP servers — each accessible at /mcp/<name>/mcp
        Mount("/mcp/db",   app=db_app),
        Mount("/mcp/geo",  app=geo_app),
        Mount("/mcp/docs", app=docs_app),
        Mount("/mcp/vector", app=vector_app),
        Mount("/mcp/map", app=map_app),

        # Existing REST API
        Route("/api/chat",                  endpoint=chat,          methods=["POST"]),
        Route("/api/documents",             endpoint=get_documents, methods=["GET"]),
        Route("/api/history/{session_id}",  endpoint=get_history,   methods=["GET"]),
        Route("/api/test-db",               endpoint=test_db,       methods=["GET"]),
        Route("/api/search",                endpoint=test_search,   methods=["GET"]),
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