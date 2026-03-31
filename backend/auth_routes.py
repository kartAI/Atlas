"""
Authentication REST endpoints.

POST /api/auth/register  — Create a new user account
POST /api/auth/login     — Log in, receive a session token
POST /api/auth/logout    — Invalidate the caller's session
GET  /api/auth/me        — Return the caller's user information

"""

import logging
from datetime import datetime, timedelta, timezone

from starlette.requests import Request
from starlette.responses import JSONResponse

from auth import generate_token, get_dummy_hash, hash_password, hash_token, verify_password
from db import execute, query

logger = logging.getLogger(__name__)

_SESSION_LIFETIME_DAYS = 7


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

async def get_user_from_request(request: Request) -> dict | None:
    """
    Validate the Bearer token in the Authorization header.

    Returns the user row dict (keys: id, email, role) when valid,
    or None when the token is absent, invalid, or expired.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    raw_token = auth_header[len("Bearer "):]
    if not raw_token:
        return None

    stored_hash = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    rows = await query(
        """
        SELECT u.id, u.email, u.role, u.is_active
        FROM app.sessions s
        JOIN app.users u ON s.user_id = u.id
        WHERE s.token_hash = %s
          AND s.expires_at > %s
          AND u.is_active = TRUE
        """,
        (stored_hash, now),
    )

    if not rows:
        return None

    return rows[0]


# ---------------------------------------------------------------------------
# Endpoint handlers
# ---------------------------------------------------------------------------

async def register(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return JSONResponse({"error": "Email and password are required."}, status_code=400)

    if len(password) < 8:
        return JSONResponse(
            {"error": "Password must be at least 8 characters."}, status_code=400
        )

    existing = await query("SELECT id FROM app.users WHERE email = %s", (email,))
    if existing:
        return JSONResponse({"error": "Email already registered."}, status_code=409)

    pw_hash = hash_password(password)

    # Do not include id - DB generates it. RETURNING id.
    rows = await query(
        """
        INSERT INTO app.users (email, password_hash)
        VALUES (%s, %s)
        RETURNING id
        """,
        (email, pw_hash),
    )
    user_id = str(rows[0]["id"])

    raw_token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=_SESSION_LIFETIME_DAYS)

    # Do not include id in INSERT.
    await execute(
        """
        INSERT INTO app.sessions (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
        """,
        (user_id, hash_token(raw_token), expires_at),
    )

    logger.info("New user registered: %s (id=%s)", email, user_id)
    return JSONResponse(
        {"token": raw_token, "user_id": user_id, "email": email},
        status_code=201,
    )


async def login(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return JSONResponse({"error": "Email and password are required."}, status_code=400)

    rows = await query(
        "SELECT id, password_hash, is_active FROM app.users WHERE email = %s",
        (email,),
    )

    # Always call verify_password. Even when no user found -> to prevent
    # timing-based enumeration of registered e-mail addresses.
    stored_hash = rows[0]["password_hash"] if rows else get_dummy_hash()
    password_matches = verify_password(password, stored_hash)

    if not rows or not password_matches:
        return JSONResponse({"error": "Invalid credentials."}, status_code=401)

    user = rows[0]
    if not user["is_active"]:
        return JSONResponse({"error": "Account is deactivated."}, status_code=403)

    raw_token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=_SESSION_LIFETIME_DAYS)
    user_id = str(user["id"])

    await execute(
        """
        INSERT INTO app.sessions (user_id, token_hash, expires_at)
        VALUES (%s, %s, %s)
        """,
        (user_id, hash_token(raw_token), expires_at),
    )

    logger.info("User logged in: %s (id=%s)", email, user_id)
    return JSONResponse({"token": raw_token, "user_id": user_id, "email": email})


async def logout(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    raw_token = auth_header[len("Bearer "):]
    await execute(
        "DELETE FROM app.sessions WHERE token_hash = %s",
        (hash_token(raw_token),),
    )
    return JSONResponse({"message": "Logged out."})


async def me(request: Request):
    user = await get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Not authenticated."}, status_code=401)

    return JSONResponse({
        "user_id": str(user["id"]),
        "email": user["email"],
        # Role is always read from DB — never from client input.
        "role": user["role"],
    })
