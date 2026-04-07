"""
Main Starlette application.

Mounts three MCP servers alongside the existing REST API:

  /mcp/db/mcp    — Database tools  (list_tables, describe_table, query_database)
  /mcp/geo/mcp   — Geo tools       (list_kommuner, list_vernetyper, buffer_search)
  /mcp/docs/mcp  — Document tools  (list_documents, fetch_document)

Auth endpoints:
  POST /api/auth/register
  POST /api/auth/login
  POST /api/auth/logout
  GET  /api/auth/me

Chat management endpoints:
  GET    /api/chats
  POST   /api/chats
  GET    /api/chats/{chat_id}/messages
  PATCH  /api/chats/{chat_id}
  DELETE /api/chats/{chat_id}

AI orchestration:
  POST /api/chat      — Send a message; persists to DB, returns AI reply
  GET  /api/documents — Azure document list
"""

import logging
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
from db import init_db_pool, close_pool, execute, execute_transaction, query
from auth_routes import (
    get_user_from_request,
    login,
    logout,
    me,
    register,
)
from chat_routes import (
    chat_detail_handler,
    chats_handler,
    get_messages,
)

# Import the MCP ASGI apps
from mcp_servers.db_server import db_app
from mcp_servers.geo_server import geo_app
from mcp_servers.docs_server import docs_app
from mcp_servers.vector_server import vector_app
from mcp_servers.map_server import map_app

logger = logging.getLogger(__name__)

# Copilot client and session manager initialization.
client = CopilotClient()
manager = SessionManager(client)

_MAX_TITLE_LENGTH = 80  # Characters from first message used as auto-title


# Lifespan, start and stop in the right order.
@asynccontextmanager
async def lifespan(app):
    async with map_app.lifespan(app):
        async with db_app.lifespan(app):
            async with geo_app.lifespan(app):
                async with docs_app.lifespan(app):
                    async with vector_app.lifespan(app):
                        await init_db_pool()
                        await client.start()
                        manager.start_cleanup_loop()
                        yield
                        manager.stop_cleanup_loop()
                        await client.stop()
                        await close_pool()


# ---------------------------------------------------------------------------
# AI orchestration endpoint
# ---------------------------------------------------------------------------

async def chat(request: Request):
    """
    POST /api/chat

    Body: { message, chat_id?, map_context? }
    Header: Authorization: Bearer <token>

    - Validates the session token and resolves the owning user.
    - If chat_id is absent a new chat is created (auto-titled from first msg).
    - Ownership of chat_id is enforced before use.
    - Loads prior DB messages for context injection into the Copilot session.
    - Persists the user message and AI reply to app.messages.
    - Returns { reply, chat_id, map_actions }.
    """
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    message = (data.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "'message' is required."}, status_code=400)
    map_context = data.get("map_context")

    chat_id: str | None = data.get("chat_id")
    created_chat = not chat_id
    user_id = str(user["id"])

    # Resolve / create the chat
    if chat_id:
        # Enforce ownership - never trust client-supplied chat_id blindly.
        ownership = await query(
            "SELECT id FROM app.chats WHERE id = %s AND user_id = %s",
            (chat_id, user_id),
        )
        if not ownership:
            return JSONResponse({"error": "Chat not found."}, status_code=404)
    else:
        # Auto-title the new chat from the first message.
        title = message[:_MAX_TITLE_LENGTH].rstrip()
        if len(message) > _MAX_TITLE_LENGTH:
            title += "…"
        rows = await query(
            """
            INSERT INTO app.chats (user_id, title)
            VALUES (%s, %s)
            RETURNING id
            """,
            (user_id, title),
        )
        chat_id = str(rows[0]["id"])

    # Load prior messages for context injection
    prior_rows = await query(
        """
        SELECT role, content
        FROM app.messages
        WHERE chat_id = %s
        ORDER BY created_at ASC
        """,
        (chat_id,),
    )
    prior_messages = [{"role": r["role"], "content": r["content"]} for r in prior_rows]

    # Get or create a live Copilot session
    try:
        copilot_session = await manager.get_or_create_for_chat(chat_id, prior_messages)
    except RuntimeError as exc:
        return JSONResponse({"error": str(exc)}, status_code=503)

    # Send to Copilot
    try:
        result = await manager.send_message(copilot_session, message, map_context=map_context, chat_id=chat_id)
    except Exception as exc:
        logger.error("Copilot send_message failed for chat %s: %s", chat_id, exc)
        return JSONResponse({"error": "AI service error. Please try again."}, status_code=502)

    reply = result["content"]
    map_actions = result["map_actions"]

    # Persist the full exchange atomically so chat history never lands half-written.
    try:
        await execute_transaction([
            (
                "INSERT INTO app.messages (chat_id, role, content) VALUES (%s, %s, %s)",
                (chat_id, "user", message),
            ),
            (
                "INSERT INTO app.messages (chat_id, role, content) VALUES (%s, %s, %s)",
                (chat_id, "assistant", reply),
            ),
            (
                "UPDATE app.chats SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (chat_id,),
            ),
        ])
    except Exception as exc:
        logger.error("Failed to persist messages for chat %s: %s", chat_id, exc)
        await manager.discard_chat(chat_id)
        if created_chat:
            try:
                await execute(
                    "DELETE FROM app.chats WHERE id = %s AND user_id = %s",
                    (chat_id, user_id),
                )
            except Exception:
                logger.warning("Failed to clean up unsaved chat %s", chat_id, exc_info=True)
        return JSONResponse({"error": "Could not save chat history. Please try again."}, status_code=500)

    return JSONResponse({"reply": reply, "chat_id": chat_id, "map_actions": map_actions})


# ---------------------------------------------------------------------------
# Other REST handlers
# ---------------------------------------------------------------------------

async def get_documents(request: Request):
    docs = list_documents()
    return JSONResponse({"documents": docs})


async def test_db(request: Request):
    if not DEMO_MODE:
        return JSONResponse({"error": "Only available in demo mode."})
    result = await query("SELECT * FROM kulturmiljoer.kommunenummer LIMIT 5")
    return JSONResponse({"data": result})


# ---------------------------------------------------------------------------
# Assemble the Starlette application
# ---------------------------------------------------------------------------

app = Starlette(
    routes=[
        # MCP servers — each accessible at /mcp/<name>/mcp
        Mount("/mcp/db",     app=db_app),
        Mount("/mcp/geo",    app=geo_app),
        Mount("/mcp/docs",   app=docs_app),
        Mount("/mcp/vector", app=vector_app),
        Mount("/mcp/map",    app=map_app),

        # Auth endpoints
        Route("/api/auth/register", endpoint=register, methods=["POST"]),
        Route("/api/auth/login",    endpoint=login,    methods=["POST"]),
        Route("/api/auth/logout",   endpoint=logout,   methods=["POST"]),
        Route("/api/auth/me",       endpoint=me,       methods=["GET"]),

        # Chat management (more-specific paths first)
        Route(
            "/api/chats/{chat_id}/messages",
            endpoint=get_messages,
            methods=["GET"],
        ),
        Route(
            "/api/chats/{chat_id}",
            endpoint=chat_detail_handler,
            methods=["PATCH", "DELETE"],
        ),
        Route(
            "/api/chats",
            endpoint=chats_handler,
            methods=["GET", "POST"],
        ),

        # AI orchestration
        Route("/api/chat",      endpoint=chat,          methods=["POST"]),

        # Miscellaneous
        Route("/api/documents", endpoint=get_documents, methods=["GET"]),
        Route("/api/test-db",   endpoint=test_db,       methods=["GET"]),
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
