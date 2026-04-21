"""
Main Starlette application.

Mounts MCP servers alongside the existing REST API:

  /mcp/db/mcp      — Database tools  (list_tables, describe_table, get_schema_overview, explain_query, query_database)
  /mcp/geo/mcp     — Geo tools       (list_kommuner, list_vernetyper, buffer_search)
  /mcp/docs/mcp    — Document tools  (list_documents, fetch_document)
  /mcp/vector/mcp  — Vector tools    (buffer, intersection, envelope, get_coordinates, point_in_polygon, get_verdensarv_sites, voronoi)
  /mcp/map/mcp     — Map tools       (draw_shape)
  /mcp/search/mcp  — Search tools    (search_documents, search_documents_fuzzy, search_documents_semantic, search_hybrid, index_*, get_indexing_status)

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
  GET  /api/search    — Quick test endpoint for document search
"""

import asyncio
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.routing import Mount, Route
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from config import ALLOWED_ORIGINS, DEMO_MODE, HOST, PORT, list_documents
from copilot import CopilotClient
from sanitizer import (
    sanitize_completed_thinking as _sanitize_completed_thinking,
    sanitize_thinking as _sanitize_thinking,
    find_pending_sql_start as _find_pending_sql,
)
from session_manager import SessionManager
from usage_tracker import get_or_create_tracker, get_tracker
from db import init_db_pool, close_pool, execute, execute_transaction, query
from tool_catalog import normalize_tool_hints
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
from layer_routes import (
    bulk_upsert_layers,
    layer_detail_handler,
    layers_handler,
)

# Import the MCP ASGI apps
from mcp_servers.db_server import db_app
from mcp_servers.geo_server import geo_app
from mcp_servers.docs_server import docs_app
from mcp_servers.vector_server import vector_app
from mcp_servers.map_server import map_app
from mcp_servers.search_server import search_app

logger = logging.getLogger(__name__)

# Copilot client and session manager initialization.
client = CopilotClient()
manager = SessionManager(client)

_MAX_TITLE_LENGTH = 80  # Characters from first message used as auto-title


# Lifespan, start and stop in the right order.
@asynccontextmanager
async def lifespan(app):
    async with db_app.lifespan(app):
        async with geo_app.lifespan(app):
            async with docs_app.lifespan(app):
                async with vector_app.lifespan(app):
                    async with map_app.lifespan(app):
                        async with search_app.lifespan(app):
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

    Body: { message, chat_id?, map_context?, stream? }
    Header: Authorization: Bearer <token>

    - Validates the session token and resolves the owning user.
    - If chat_id is absent a new chat is created (auto-titled from first msg).
    - Ownership of chat_id is enforced before use.
    - Loads prior DB messages for context injection into the Copilot session.
    - Persists the user message and AI reply to app.messages.
    - If stream=true, returns SSE events; otherwise returns JSON { reply, chat_id, map_actions }.
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
    if len(message) > 10000:
        return JSONResponse({"error": "Message too long."}, status_code=400)
    map_context = data.get("map_context")
    tool_hints = normalize_tool_hints(data.get("tool_hints"))
    stream = data.get("stream") is True

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

    # Start usage tracking for this turn.
    tracker = get_or_create_tracker(chat_id)
    turn_id = f"{chat_id}-{len(prior_messages) // 2}"
    tracker.start_turn(turn_id)

    if stream:
        return StreamingResponse(
            _stream_chat(copilot_session, message, map_context, chat_id, user_id, created_chat, tool_hints, tracker),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Content-Type-Options": "nosniff",
            },
        )

    # Non-streaming fallback (original behaviour)
    try:
        result = await manager.send_message(copilot_session, message, map_context=map_context, chat_id=chat_id, tool_hints=tool_hints)
    except Exception as exc:
        # Finalise the turn even on error so partial data isn't lost.
        tracker.finalise_turn()
        logger.error("Copilot send_message failed for chat %s: %s", chat_id, exc)
        return JSONResponse({"error": "AI service error. Please try again."}, status_code=502)

    reply = result["content"]
    map_actions = result["map_actions"]

    # Assign stable layer_ids to AI-generated layers so the frontend can reference them.
    for action in map_actions:
        action["layer_id"] = f"drawn-{int(time.time() * 1000)}-{secrets.token_hex(3)}"

    # Finalise usage tracking for this turn.
    turn_usage = tracker.finalise_turn()
    usage_snapshot = tracker.snapshot(turn_usage)

    # Persist the full exchange + AI layers atomically.
    user_meta = json.dumps({"tool_hints": tool_hints}) if tool_hints else None
    tx_statements = [
        (
            "INSERT INTO app.messages (chat_id, role, content, metadata) VALUES (%s, %s, %s, %s::jsonb)",
            (chat_id, "user", message, user_meta),
        ),
        (
            "INSERT INTO app.messages (chat_id, role, content, metadata) VALUES (%s, %s, %s, %s::jsonb)",
            (chat_id, "assistant", reply, None),
        ),
        (
            "UPDATE app.chats SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (chat_id,),
        ),
    ]

    for action in map_actions:
        geojson = action.get("geojson")
        if not geojson or not isinstance(geojson, dict):
            continue
        shape = geojson.get("type", "Feature")
        if shape == "FeatureCollection":
            pass  # keep as-is
        elif geojson.get("geometry"):
            shape = geojson["geometry"].get("type", "Feature")
        tx_statements.append((
            """
            INSERT INTO app.chat_layers (chat_id, layer_id, name, shape, visible, geojson)
            VALUES (%s, %s, %s, %s, TRUE, %s::jsonb)
            ON CONFLICT (chat_id, layer_id)
            DO UPDATE SET name = EXCLUDED.name, shape = EXCLUDED.shape,
                          geojson = EXCLUDED.geojson, updated_at = now()
            """,
            (
                chat_id,
                action["layer_id"],
                action.get("layer_name", "AI-lag"),
                shape,
                json.dumps(geojson),
            ),
        ))

    try:
        await execute_transaction(tx_statements)
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

    return JSONResponse({
        "reply": reply,
        "chat_id": chat_id,
        "map_actions": map_actions,
        "usage": usage_snapshot,
    })


async def _stream_chat(copilot_session, message, map_context, chat_id, user_id, created_chat, tool_hints, tracker):
    """
    Async generator that yields SSE events for a streaming chat response.

    Event types:
      event: meta       — { chat_id }
      event: thinking   — { content: "delta..." }
      event: delta      — { content: "delta..." }
      event: done       — { content, map_actions, usage }
      event: error      — { error: "..." }
    """

    # Immediately tell the client which chat_id to use
    yield f"event: meta\ndata: {json.dumps({'chat_id': chat_id})}\n\n"

    # Holdback buffer size — chars withheld from the client until the next
    # chunk (or final flush) so that patterns split across chunk boundaries
    # are never partially emitted before the sanitizer can recognise them.
    _THINKING_HOLDBACK = 128
    _MAX_THINKING_CHARS = 100_000
    _THINKING_TRUNCATED_MARKER = "[thinking truncated]"

    reply = ""
    raw_thinking = ""       # unsanitized accumulation for full-text re-sanitization
    chars_sent = 0          # sanitized chars already emitted to client
    map_actions = []
    thinking_truncated = False

    def _finalize_thinking_text(raw_text: str, *, truncated: bool) -> str:
        text = _sanitize_completed_thinking(raw_text)
        if not truncated:
            return text
        safe_end = max(0, len(text) - _THINKING_HOLDBACK)
        text = text[:safe_end]
        if text:
            return f"{text}\n{_THINKING_TRUNCATED_MARKER}"
        return _THINKING_TRUNCATED_MARKER

    try:
        async for chunk in manager.send_message_stream(
            copilot_session, message,
            map_context=map_context, chat_id=chat_id, tool_hints=tool_hints,
        ):
            ctype = chunk["type"]
            if ctype == "thinking":
                if thinking_truncated:
                    continue
                raw_thinking += chunk["content"]
                if len(raw_thinking) > _MAX_THINKING_CHARS:
                    # Safety cutoff to prevent memory issues from runaway thinking text.
                    raw_thinking = raw_thinking[:_MAX_THINKING_CHARS]
                    thinking_truncated = True
                # Re-sanitize the full accumulated text so patterns that span
                # chunk boundaries are caught.
                full_sanitized = _sanitize_thinking(raw_thinking)

                # Safe emission boundary: hold back _THINKING_HOLDBACK chars
                # for short patterns, and everything from an unterminated SQL
                # keyword onward.  We search the *sanitized* text so offsets
                # stay valid after earlier rules shorten it.
                safe_end = max(chars_sent, len(full_sanitized) - _THINKING_HOLDBACK)
                pending_sql = _find_pending_sql(full_sanitized)
                if pending_sql >= 0:
                    # Suppress all output from the SQL keyword onward.
                    safe_end = min(safe_end, pending_sql)
                    safe_end = max(safe_end, chars_sent)  # never go backwards

                if safe_end > chars_sent:
                    delta = full_sanitized[chars_sent:safe_end]
                    yield f"event: thinking\ndata: {json.dumps({'content': delta})}\n\n"
                    chars_sent = safe_end
            elif ctype == "delta":
                yield f"event: delta\ndata: {json.dumps({'content': chunk['content']})}\n\n"
            elif ctype == "done":
                reply = chunk["content"]
                map_actions = chunk["map_actions"]

    except asyncio.CancelledError:
        # Client disconnected — clean up silently.
        tracker.finalise_turn()
        logger.info("Stream cancelled (client disconnect) for chat %s", chat_id)
        return

    except Exception as exc:
        tracker.finalise_turn()
        logger.error("Streaming failed for chat %s: %s", chat_id, exc)
        yield f"event: error\ndata: {json.dumps({'error': 'AI service error. Please try again.'})}\n\n"
        return

    # Flush any held-back thinking text now that no more chunks can arrive.
    if raw_thinking:
        full_sanitized = _finalize_thinking_text(raw_thinking, truncated=thinking_truncated)
        if len(full_sanitized) > chars_sent:
            remaining = full_sanitized[chars_sent:]
            yield f"event: thinking\ndata: {json.dumps({'content': remaining})}\n\n"

    # Assign stable layer_ids to AI-generated layers (mirrors non-streaming path).
    for action in map_actions:
        action["layer_id"] = f"drawn-{int(time.time() * 1000)}-{secrets.token_hex(3)}"

    turn_usage = tracker.finalise_turn()
    usage_snapshot = tracker.snapshot(turn_usage)

    # Re-sanitize the full thinking text for persistent storage — ensures
    # patterns split across streaming chunks are properly redacted at rest.
    thinking_text = (
        _finalize_thinking_text(raw_thinking, truncated=thinking_truncated)
        if raw_thinking else ""
    )

    # Persist the full exchange + AI layers atomically.
    user_meta = json.dumps({"tool_hints": tool_hints}) if tool_hints else None
    asst_meta = json.dumps({"thinking": thinking_text}) if thinking_text else None
    tx_statements = [
        (
            "INSERT INTO app.messages (chat_id, role, content, metadata) VALUES (%s, %s, %s, %s::jsonb)",
            (chat_id, "user", message, user_meta),
        ),
        (
            "INSERT INTO app.messages (chat_id, role, content, metadata) VALUES (%s, %s, %s, %s::jsonb)",
            (chat_id, "assistant", reply, asst_meta),
        ),
        (
            "UPDATE app.chats SET updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (chat_id,),
        ),
    ]

    for action in map_actions:
        geojson = action.get("geojson")
        if not geojson or not isinstance(geojson, dict):
            continue
        shape = geojson.get("type", "Feature")
        if shape == "FeatureCollection":
            pass  # keep as-is
        elif geojson.get("geometry"):
            shape = geojson["geometry"].get("type", "Feature")
        tx_statements.append((
            """
            INSERT INTO app.chat_layers (chat_id, layer_id, name, shape, visible, geojson)
            VALUES (%s, %s, %s, %s, TRUE, %s::jsonb)
            ON CONFLICT (chat_id, layer_id)
            DO UPDATE SET name = EXCLUDED.name, shape = EXCLUDED.shape,
                          geojson = EXCLUDED.geojson, updated_at = now()
            """,
            (
                chat_id,
                action["layer_id"],
                action.get("layer_name", "AI-lag"),
                shape,
                json.dumps(geojson),
            ),
        ))

    try:
        await execute_transaction(tx_statements)
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
        yield f"event: error\ndata: {json.dumps({'error': 'Could not save chat history.'})}\n\n"
        return

    yield f"event: done\ndata: {json.dumps({'content': reply, 'map_actions': map_actions, 'usage': usage_snapshot})}\n\n"


# ---------------------------------------------------------------------------
# Usage query endpoint
# ---------------------------------------------------------------------------

async def get_usage(request: Request):
    """
    GET /api/usage?chat_id=<uuid>

    Returns the current usage snapshot for a chat session.
    If no chat_id is provided, returns an empty/unavailable snapshot.
    """
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.query_params.get("chat_id")
    if not chat_id:
        return JSONResponse({"usage": {
            "turn": None,
            "session": None,
            "monthly": {"confidence": "unavailable"},
        }})

    # Enforce ownership.
    user_id = str(user["id"])
    ownership = await query(
        "SELECT id FROM app.chats WHERE id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    if not ownership:
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    tracker = get_tracker(chat_id)
    if not tracker:
        return JSONResponse({"usage": {
            "turn": None,
            "session": None,
            "monthly": {"confidence": "unavailable"},
        }})

    return JSONResponse({"usage": tracker.snapshot()})


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


async def test_search(request: Request):
    """Quick REST endpoint to test document search without MCP protocol."""
    if not DEMO_MODE:
        return JSONResponse({"error": "Only available in demo mode."}, status_code=403)
    q = request.query_params.get("q", "")
    if not q:
        return JSONResponse({"error": "Bruk ?q=søkeord"}, status_code=400)
    from search_service import search_full_text, search_fuzzy, search_semantic, hybrid_search
    mode = request.query_params.get("mode", "fulltext")
    if mode == "fuzzy":
        results = await search_fuzzy(q)
    elif mode == "semantic":
        results = await search_semantic(q)
    elif mode == "hybrid":
        results = await hybrid_search(q)
    else:
        results = await search_full_text(q)
    return JSONResponse({"query": q, "mode": mode, "count": len(results), "results": results})


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
        Mount("/mcp/search", app=search_app),

        # Auth endpoints
        Route("/api/auth/register", endpoint=register, methods=["POST"]),
        Route("/api/auth/login",    endpoint=login,    methods=["POST"]),
        Route("/api/auth/logout",   endpoint=logout,   methods=["POST"]),
        Route("/api/auth/me",       endpoint=me,       methods=["GET"]),

        # Chat management (more-specific paths first)
        Route(
            "/api/chats/{chat_id}/layers/bulk",
            endpoint=bulk_upsert_layers,
            methods=["POST"],
        ),
        Route(
            "/api/chats/{chat_id}/layers/{layer_id}",
            endpoint=layer_detail_handler,
            methods=["PATCH", "DELETE"],
        ),
        Route(
            "/api/chats/{chat_id}/layers",
            endpoint=layers_handler,
            methods=["GET", "POST"],
        ),
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

        # Usage tracking
        Route("/api/usage",     endpoint=get_usage,     methods=["GET"]),

        # Miscellaneous
        Route("/api/documents", endpoint=get_documents, methods=["GET"]),
        Route("/api/test-db",   endpoint=test_db,       methods=["GET"]),
        Route("/api/search",    endpoint=test_search,   methods=["GET"]),
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
