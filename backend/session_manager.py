import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from copilot import CopilotClient, PermissionHandler
from config import (
    DEMO_MODE,
    MAX_HISTORY_PER_SESSION,
    MAX_SESSIONS,
    MODEL_NAME,
    SESSION_TIMEOUT_MINUTES,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")


def strict_permission_handler(*_args, **_kwargs):
    """Deny tool permission requests by default outside demo mode."""
    return False

def allow_all_permission_handler(*_args, **_kwargs):
    """Allow tool permission requests in demo mode when SDK helpers are unavailable."""
    return True


class SessionManager:
    def __init__(self, client: CopilotClient, timeout_minutes=SESSION_TIMEOUT_MINUTES):
        self.client = client
        self.sessions = {}
        self.last_active = {}
        self.history = {}
        self.timeout = timedelta(minutes=timeout_minutes)
        self.max_sessions = MAX_SESSIONS
        self.max_history = MAX_HISTORY_PER_SESSION
        self._cleanup_task = None

        if not SERVER_BASE_URL.startswith("https://") and "localhost" not in SERVER_BASE_URL:
            logger.warning(
                "SERVER_BASE_URL is not HTTPS (%s) — ensure HTTPS in production",
                SERVER_BASE_URL,
            )

    def start_cleanup_loop(self, interval_seconds=60):
        """Start a background task that periodically removes expired sessions."""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop(interval_seconds))
        logger.info("Session cleanup loop started (interval=%ds)", interval_seconds)

    async def _cleanup_loop(self, interval_seconds):
        while True:
            await asyncio.sleep(interval_seconds)
            await self.cleanup_expired()

    def stop_cleanup_loop(self):
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            logger.info("Session cleanup loop stopped")

    async def get_or_create(self, session_id=None):
        if session_id and session_id in self.sessions:
            self.last_active[session_id] = datetime.now(timezone.utc)
            return session_id, self.sessions[session_id]

        if len(self.sessions) >= self.max_sessions:
            raise RuntimeError(
                f"Maximum number of concurrent sessions ({self.max_sessions}) reached"
            )

        session_id = str(uuid.uuid4())

        sdk_approve_all_handler = getattr(PermissionHandler, "approve_all", None)
        sdk_reject_all_handler = getattr(PermissionHandler, "reject_all", None)
        if DEMO_MODE:
            permission_handler = (
                sdk_approve_all_handler
                if callable(sdk_approve_all_handler)
                else allow_all_permission_handler
            )
        else:
            permission_handler = (
                sdk_reject_all_handler
                if callable(sdk_reject_all_handler)
                else strict_permission_handler
            )

        session = await self.client.create_session({
            "model": MODEL_NAME,
            "system_message": {
                "mode": "append",
                "content": SYSTEM_PROMPT
            },

            # The orchestrator (Copilot) can now pick from three specialised servers:
            #   - db:          raw SQL tools for exploring and querying the database
            #   - geo_server:  domain-specific geo/KU tools (buffer search, kommuner etc.)
            #   - docs_server: Azure Blob document tools (list + fetch PDFs)
            #   - vector_server: Vector-based spatial analysis tools (buffer, intersection)
            # Add new MCP servers here as you build them.
            "mcp_servers": {
                "database": {
                    "type": "http",
                    "url": f"{SERVER_BASE_URL}/mcp/db/mcp",
                    "tools": ["*"],
                },
                "geo": {
                    "type": "http",
                    "url": f"{SERVER_BASE_URL}/mcp/geo/mcp",
                    "tools": ["*"],
                },
                "docs": {
                    "type": "http",
                    "url": f"{SERVER_BASE_URL}/mcp/docs/mcp",
                    "tools": ["*"],
                },
                "vector": {
                    "type": "http",
                    "url": f"{SERVER_BASE_URL}/mcp/vector/mcp",
                    "tools": ["*"],
                },
            },
            "on_permission_request": permission_handler,
        })

        self.sessions[session_id] = session
        self.last_active[session_id] = datetime.now(timezone.utc)
        self.history[session_id] = []
        logger.info("Session created: %s (active=%d)", session_id, len(self.sessions))
        return session_id, session

    async def send_message(self, session_id, message):
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found or expired")

        self.last_active[session_id] = datetime.now(timezone.utc)

        response = await session.send_and_wait({"prompt": message}, timeout=180)
        content = response.data.content

        self.history[session_id].append({"role": "user", "content": message})
        self.history[session_id].append({"role": "assistant", "content": content})

        if len(self.history[session_id]) > self.max_history:
            self.history[session_id] = self.history[session_id][-self.max_history:]

        return content

    async def cleanup_expired(self):
        now = datetime.now(timezone.utc)
        expired = [
            sid for sid, last in self.last_active.items()
            if now - last > self.timeout
        ]
        for sid in expired:
            try:
                await self.sessions[sid].destroy()
            except Exception:
                logger.warning("Failed to destroy session %s", sid, exc_info=True)
            del self.sessions[sid]
            del self.last_active[sid]
            del self.history[sid]
            logger.info("Session expired and removed: %s", sid)

    def get_history(self, session_id):
        return list(self.history.get(session_id, []))