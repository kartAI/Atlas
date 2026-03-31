"""
Chat persistence REST endpoints.

GET    /api/chats                     — List the authenticated user's chats
POST   /api/chats                     — Create a new chat
GET    /api/chats/{chat_id}/messages  — Load all messages for a chat
PATCH  /api/chats/{chat_id}           — Update chat title
DELETE /api/chats/{chat_id}           — Delete a chat and all its messages

Security rules (from prompt.txt):
- Users can only access their own chats (ownership enforced on every query).
- Messages must belong to chats owned by the user.
- Parameterized queries only; no string interpolation.
- Only operate within schema app.
"""

import logging
from datetime import datetime

from starlette.requests import Request
from starlette.responses import JSONResponse

from auth_routes import get_user_from_request
from db import execute, query

logger = logging.getLogger(__name__)

_MAX_TITLE_LENGTH = 200


# ---------------------------------------------------------------------------
# Serialisation helper
# ---------------------------------------------------------------------------

def _serialize_rows(rows: list) -> list:
    """
    Convert psycopg dict_row objects to JSON-safe dicts.
    uuid.UUID  → str
    datetime   → ISO 8601 string
    """
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                item[key] = value.isoformat()
            elif hasattr(value, "hex"):  # uuid.UUID
                item[key] = str(value)
            else:
                item[key] = value
        result.append(item)
    return result


def _serialize_row(row: dict) -> dict:
    return _serialize_rows([row])[0]


# ---------------------------------------------------------------------------
# Ownership enforcement helper
# ---------------------------------------------------------------------------

async def _assert_chat_owner(chat_id: str, user_id: str) -> bool:
    """Return True if the user owns chat_id, False otherwise."""
    rows = await query(
        "SELECT id FROM app.chats WHERE id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return bool(rows)


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def list_chats(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    rows = await query(
        """
        SELECT id, title, created_at, updated_at
        FROM app.chats
        WHERE user_id = %s
        ORDER BY updated_at DESC
        """,
        (str(user["id"]),),
    )
    return JSONResponse({"chats": _serialize_rows(rows)})


async def create_chat(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    try:
        data = await request.json()
    except Exception:
        data = {}

    title = (data.get("title") or "Ny samtale").strip()[:_MAX_TITLE_LENGTH]

    # Do NOT include id — DB generates it. RETURNING id to retrieve it.
    rows = await query(
        """
        INSERT INTO app.chats (user_id, title)
        VALUES (%s, %s)
        RETURNING id, title, created_at, updated_at
        """,
        (str(user["id"]), title),
    )
    return JSONResponse(_serialize_row(rows[0]), status_code=201)


async def get_messages(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    rows = await query(
        """
        SELECT id, role, content, metadata, created_at
        FROM app.messages
        WHERE chat_id = %s
        ORDER BY created_at ASC
        """,
        (chat_id,),
    )
    return JSONResponse({"messages": _serialize_rows(rows)})


async def update_chat(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    title = (data.get("title") or "").strip()[:_MAX_TITLE_LENGTH]
    if not title:
        return JSONResponse({"error": "Title is required."}, status_code=400)

    rows = await query(
        """
        UPDATE app.chats
        SET title = %s
        WHERE id = %s AND user_id = %s
        RETURNING id, title, updated_at
        """,
        (title, chat_id, user_id),
    )
    return JSONResponse(_serialize_row(rows[0]))


async def delete_chat(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    # CASCADE on app.messages and app.chat_artifacts handles child rows.
    await execute(
        "DELETE FROM app.chats WHERE id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return JSONResponse({"message": "Chat deleted."})


# ---------------------------------------------------------------------------
# Router-level dispatch helpers (single path, multiple methods)
# ---------------------------------------------------------------------------

async def chats_handler(request: Request):
    """Dispatch GET /api/chats and POST /api/chats."""
    if request.method == "GET":
        return await list_chats(request)
    return await create_chat(request)


async def chat_detail_handler(request: Request):
    """Dispatch PATCH /api/chats/{chat_id} and DELETE /api/chats/{chat_id}."""
    if request.method == "PATCH":
        return await update_chat(request)
    return await delete_chat(request)
