"""
Authentication utilities.

- Passwords : bcrypt
- Tokens    : secrets.token_urlsafe(32) → raw token returned to client
              SHA-256 digest stored in app.sessions.token_hash
"""

import hashlib
import secrets

import bcrypt

# Pre-warmed dummy hash used to keep login timings constant regardless
# of whether the queried e-mail exists in the database.
_DUMMY_HASH: str = bcrypt.hashpw(b"geo_mcp_dummy_warmup", bcrypt.gensalt()).decode("utf-8")


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the given plaintext password."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Verify *plain* against a stored bcrypt *hashed* value.

    Returns False (instead of raising) if the hash is malformed so the caller
    can treat any non-matching value as an authentication failure.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def get_dummy_hash() -> str:
    """Return the module-level dummy hash for constant-time login checks."""
    return _DUMMY_HASH


def generate_token() -> str:
    """Generate a cryptographically secure URL-safe token (~256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    """Return the SHA-256 hex digest of *raw* for safe storage in the database."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
