"""
Layer persistence REST endpoints.

GET    /api/chats/{chat_id}/layers              — List all layers for a chat
POST   /api/chats/{chat_id}/layers              — Create or upsert a single layer
POST   /api/chats/{chat_id}/layers/bulk         — Bulk-create layers
PATCH  /api/chats/{chat_id}/layers/{layer_id}   — Update a layer (visibility, name, geometry)
DELETE /api/chats/{chat_id}/layers/{layer_id}    — Delete a single layer

Security rules:
- Users can only access layers belonging to their own chats.
- Parameterized queries only; no string interpolation.
- Only operate within schema app.
"""

import json
import logging
import uuid as _uuid
from datetime import datetime

from starlette.requests import Request
from starlette.responses import JSONResponse

from auth_routes import get_user_from_request
from db import execute, execute_transaction, query

logger = logging.getLogger(__name__)

_MAX_LAYER_ID_LENGTH = 100
_MAX_NAME_LENGTH = 200
_MAX_SHAPE_LENGTH = 50
_MAX_GEOJSON_BYTES = 5 * 1024 * 1024  # 5 MB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_uuid(value: str) -> bool:
    try:
        _uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _serialize_rows(rows: list) -> list:
    result = []
    for row in rows:
        item = {}
        for key, value in row.items():
            if isinstance(value, datetime):
                item[key] = value.isoformat()
            elif hasattr(value, "hex"):
                item[key] = str(value)
            else:
                item[key] = value
        result.append(item)
    return result


async def _assert_chat_owner(chat_id: str, user_id: str) -> bool:
    rows = await query(
        "SELECT id FROM app.chats WHERE id = %s AND user_id = %s",
        (chat_id, user_id),
    )
    return bool(rows)


def _validate_layer(data: dict) -> str | None:
    """Return an error message string if validation fails, else None."""
    layer_id = data.get("layer_id")
    name = data.get("name")
    shape = data.get("shape")
    geojson = data.get("geojson")

    if not layer_id or not isinstance(layer_id, str):
        return "'layer_id' is required."
    if len(layer_id) > _MAX_LAYER_ID_LENGTH:
        return f"'layer_id' exceeds {_MAX_LAYER_ID_LENGTH} characters."
    if not name or not isinstance(name, str):
        return "'name' is required."
    if len(name) > _MAX_NAME_LENGTH:
        return f"'name' exceeds {_MAX_NAME_LENGTH} characters."
    if not shape or not isinstance(shape, str):
        return "'shape' is required."
    if len(shape) > _MAX_SHAPE_LENGTH:
        return f"'shape' exceeds {_MAX_SHAPE_LENGTH} characters."
    if not geojson or not isinstance(geojson, dict):
        return "'geojson' must be a non-empty object."
    if len(json.dumps(geojson)) > _MAX_GEOJSON_BYTES:
        return f"'geojson' exceeds {_MAX_GEOJSON_BYTES // (1024 * 1024)} MB limit."
    return None


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def list_layers(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    if not _is_valid_uuid(chat_id):
        return JSONResponse({"error": "Invalid chat ID."}, status_code=400)
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    rows = await query(
        """
        SELECT layer_id, name, shape, visible, geojson, created_at, updated_at
        FROM app.chat_layers
        WHERE chat_id = %s
        ORDER BY created_at ASC
        """,
        (chat_id,),
    )
    return JSONResponse({"layers": _serialize_rows(rows)})


async def upsert_layer(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    if not _is_valid_uuid(chat_id):
        return JSONResponse({"error": "Invalid chat ID."}, status_code=400)
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    error = _validate_layer(data)
    if error:
        return JSONResponse({"error": error}, status_code=400)

    visible = bool(data.get("visible", True))

    await execute(
        """
        INSERT INTO app.chat_layers (chat_id, layer_id, name, shape, visible, geojson)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (chat_id, layer_id)
        DO UPDATE SET name     = EXCLUDED.name,
                      shape    = EXCLUDED.shape,
                      visible  = EXCLUDED.visible,
                      geojson  = EXCLUDED.geojson,
                      updated_at = now()
        """,
        (
            chat_id,
            data["layer_id"][:_MAX_LAYER_ID_LENGTH],
            data["name"][:_MAX_NAME_LENGTH],
            data["shape"][:_MAX_SHAPE_LENGTH],
            visible,
            json.dumps(data["geojson"]),
        ),
    )
    return JSONResponse({"status": "ok"}, status_code=200)


async def bulk_upsert_layers(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    if not _is_valid_uuid(chat_id):
        return JSONResponse({"error": "Invalid chat ID."}, status_code=400)
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    layers = data.get("layers")
    if not isinstance(layers, list):
        return JSONResponse({"error": "'layers' must be an array."}, status_code=400)

    if len(layers) > 200:
        return JSONResponse({"error": "Too many layers (max 200)."}, status_code=400)

    for i, layer in enumerate(layers):
        error = _validate_layer(layer)
        if error:
            return JSONResponse({"error": f"Layer {i}: {error}"}, status_code=400)

    tx_statements = []
    for layer in layers:
        visible = bool(layer.get("visible", True))
        tx_statements.append((
            """
            INSERT INTO app.chat_layers (chat_id, layer_id, name, shape, visible, geojson)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (chat_id, layer_id)
            DO UPDATE SET name     = EXCLUDED.name,
                          shape    = EXCLUDED.shape,
                          visible  = EXCLUDED.visible,
                          geojson  = EXCLUDED.geojson,
                          updated_at = now()
            """,
            (
                chat_id,
                layer["layer_id"][:_MAX_LAYER_ID_LENGTH],
                layer["name"][:_MAX_NAME_LENGTH],
                layer["shape"][:_MAX_SHAPE_LENGTH],
                visible,
                json.dumps(layer["geojson"]),
            ),
        ))

    await execute_transaction(tx_statements)

    return JSONResponse({"status": "ok", "count": len(layers)}, status_code=200)


async def update_layer(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    layer_id = request.path_params["layer_id"]
    if not _is_valid_uuid(chat_id):
        return JSONResponse({"error": "Invalid chat ID."}, status_code=400)
    if len(layer_id) > _MAX_LAYER_ID_LENGTH:
        return JSONResponse({"error": "Invalid layer ID."}, status_code=400)
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    # Build SET clauses dynamically for provided fields only.
    set_parts = []
    params = []

    if "visible" in data:
        set_parts.append("visible = %s")
        params.append(bool(data["visible"]))

    if "name" in data:
        name = (data["name"] or "").strip()[:_MAX_NAME_LENGTH]
        if not name:
            return JSONResponse({"error": "'name' cannot be empty."}, status_code=400)
        set_parts.append("name = %s")
        params.append(name)

    if "shape" in data:
        shape_val = (data["shape"] or "")[:_MAX_SHAPE_LENGTH]
        if not shape_val:
            return JSONResponse({"error": "'shape' cannot be empty."}, status_code=400)
        set_parts.append("shape = %s")
        params.append(shape_val)

    if "geojson" in data:
        geojson = data["geojson"]
        if not isinstance(geojson, dict):
            return JSONResponse({"error": "'geojson' must be an object."}, status_code=400)
        if len(json.dumps(geojson)) > _MAX_GEOJSON_BYTES:
            return JSONResponse(
                {"error": f"'geojson' exceeds {_MAX_GEOJSON_BYTES // (1024 * 1024)} MB limit."},
                status_code=400,
            )
        set_parts.append("geojson = %s::jsonb")
        params.append(json.dumps(geojson))

    if not set_parts:
        return JSONResponse({"error": "No fields to update."}, status_code=400)

    set_parts.append("updated_at = now()")
    set_clause = ", ".join(set_parts)
    params.extend([chat_id, layer_id])

    rows = await query(
        f"UPDATE app.chat_layers SET {set_clause} WHERE chat_id = %s AND layer_id = %s RETURNING layer_id",
        tuple(params),
    )
    if not rows:
        return JSONResponse({"error": "Layer not found."}, status_code=404)

    return JSONResponse({"status": "ok"})


async def delete_layer(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    chat_id = request.path_params["chat_id"]
    layer_id = request.path_params["layer_id"]
    if not _is_valid_uuid(chat_id):
        return JSONResponse({"error": "Invalid chat ID."}, status_code=400)
    if len(layer_id) > _MAX_LAYER_ID_LENGTH:
        return JSONResponse({"error": "Invalid layer ID."}, status_code=400)
    user_id = str(user["id"])

    if not await _assert_chat_owner(chat_id, user_id):
        return JSONResponse({"error": "Chat not found."}, status_code=404)

    await execute(
        "DELETE FROM app.chat_layers WHERE chat_id = %s AND layer_id = %s",
        (chat_id, layer_id),
    )
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Router-level dispatch helpers
# ---------------------------------------------------------------------------

async def layers_handler(request: Request):
    """Dispatch GET and POST for /api/chats/{chat_id}/layers."""
    if request.method == "GET":
        return await list_layers(request)
    return await upsert_layer(request)


async def layer_detail_handler(request: Request):
    """Dispatch PATCH and DELETE for /api/chats/{chat_id}/layers/{layer_id}."""
    if request.method == "PATCH":
        return await update_layer(request)
    return await delete_layer(request)
