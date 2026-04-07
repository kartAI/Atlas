import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from copilot import CopilotClient, PermissionHandler
from mcp_servers.map_server import get_and_clear_shapes
from config import (
    DEMO_MODE,
    MAX_SESSIONS,
    MODEL_NAME,
    SESSION_TIMEOUT_MINUTES,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")

# Maximum number of prior messages injected as context when resuming a chat.
_MAX_CONTEXT_MESSAGES = 30
# Maximum characters per message used in the context injection.
_MAX_CONTEXT_CHARS = 1000

def strict_permission_handler(*_args, **_kwargs):
    """Deny tool permission requests by default outside demo mode."""
    return False

def allow_all_permission_handler(*_args, **_kwargs):
    """Allow tool permission requests in demo mode when SDK helpers are unavailable."""
    return True


class SessionManager:
    """
    Maps DB chat IDs to live Copilot SDK sessions.

    History is now stored in PostgreSQL (app.messages); this class keeps only
    the in-memory Copilot sessions and their last-active timestamps.
    """

    def __init__(self, client: CopilotClient, timeout_minutes=SESSION_TIMEOUT_MINUTES):
        self.client = client
        # sessions: chat_id (str) -> Copilot session object
        self.sessions: dict = {}
        self.last_active: dict = {}
        self.timeout = timedelta(minutes=timeout_minutes)
        self.max_sessions = MAX_SESSIONS
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

    async def get_or_create_for_chat(
        self,
        chat_id: str,
        prior_messages: list | None = None,
    ):
        """
        Return (or create) the live Copilot session for *chat_id*.

        When no live session exists (new chat or server restart), a new
        Copilot session is created.  If *prior_messages* is provided the
        last _MAX_CONTEXT_MESSAGES entries are injected into the system
        message so the model has continuity when resuming a conversation.

        Raises RuntimeError if the session cap is reached.
        """
        if chat_id in self.sessions:
            self.last_active[chat_id] = datetime.now(timezone.utc)
            return self.sessions[chat_id]

        if len(self.sessions) >= self.max_sessions:
            raise RuntimeError(
                f"Maximum number of concurrent sessions ({self.max_sessions}) reached"
            )

        sdk_approve_all = getattr(PermissionHandler, "approve_all", None)
        sdk_reject_all = getattr(PermissionHandler, "reject_all", None)
        if DEMO_MODE:
            permission_handler = (
                sdk_approve_all if callable(sdk_approve_all) else allow_all_permission_handler
            )
        else:
            permission_handler = (
                sdk_reject_all if callable(sdk_reject_all) else strict_permission_handler
            )

        system_content = SYSTEM_PROMPT
        if prior_messages:
            system_content = SYSTEM_PROMPT + self._build_history_context(prior_messages)

        session = await self.client.create_session({
            "model": MODEL_NAME,
            "system_message": {
                "mode": "append",
                "content": system_content,
            },
            # MCP servers the orchestrator can invoke.
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
                "map": {
                    "type": "http",
                    "url": f"{SERVER_BASE_URL}/mcp/map/mcp",
                    "tools": ["*"],
                },
            },
            "on_permission_request": permission_handler,
        })

        self.sessions[chat_id] = session
        self.last_active[chat_id] = datetime.now(timezone.utc)
        logger.info(
            "Copilot session created for chat %s (active=%d)", chat_id, len(self.sessions)
        )
        return session

    def _build_history_context(self, messages: list) -> str:
        """
        Build a readable history block from *messages* to append to the system
        prompt so the model can resume a conversation with context.

        Only the last _MAX_CONTEXT_MESSAGES are used; each message is truncated
        to _MAX_CONTEXT_CHARS characters to keep the prompt within limits.
        """
        recent = messages[-_MAX_CONTEXT_MESSAGES:]
        SEP = "─" * 80
        lines = [
            f"\n\n{SEP}\n"
            "SAMTALEHISTORIKK (tidligere meldinger i denne samtalen)\n"
            f"{SEP}"
        ]
        for msg in recent:
            role_label = "Bruker" if msg.get("role") == "user" else "Assistent"
            content = (msg.get("content") or "")[:_MAX_CONTEXT_CHARS]
            if len(msg.get("content") or "") > _MAX_CONTEXT_CHARS:
                content += "…"
            lines.append(f"\n{role_label}: {content}")
        lines.append(
            f"\n{SEP}\n"
            "Fortsett samtalen fra der den slapp av."
        )
        return "".join(lines)

    async def send_message(self, session, message: str, map_context=None, chat_id: str = "") -> dict:
        """
        Send *message* to an active Copilot *session* and return a dict with
        the reply content and any pending map actions.

        Callers are responsible for persisting messages to the database.
        """
        if map_context:
            layer_summary = "\n".join(
                f"- {l.get('name', 'Unnamed')} ({l.get('shape', '?')}): {json.dumps(l.get('geoJson'))}"
                for l in map_context
            )
            full_message = f"[SESSION_ID: {chat_id}]\n[CURRENT MAP STATE]\n{layer_summary}\n\n[USER MESSAGE]\n{message}"
        elif chat_id:
            full_message = f"[SESSION_ID: {chat_id}]\n\n[USER MESSAGE]\n{message}"
        else:
            full_message = message

        try:
            response = await session.send_and_wait({"prompt": full_message}, timeout=180)
        except Exception:
            # Evict the broken session so the next request creates a fresh one
            # instead of retrying against a permanently dead session.
            if chat_id and chat_id in self.sessions:
                self.sessions.pop(chat_id, None)
                self.last_active.pop(chat_id, None)
                logger.warning(
                    "Evicted broken session for chat %s; will recreate on next request",
                    chat_id,
                )
            raise

        content = response.data.content
        map_actions = get_and_clear_shapes(chat_id)
        return {"content": content, "map_actions": map_actions}

    async def cleanup_expired(self):
        now = datetime.now(timezone.utc)
        expired = [
            chat_id
            for chat_id, last in self.last_active.items()
            if now - last > self.timeout
        ]
        for chat_id in expired:
            try:
                await self.sessions[chat_id].destroy()
            except Exception:
                logger.warning(
                    "Failed to destroy session for chat %s", chat_id, exc_info=True
                )
            del self.sessions[chat_id]
            del self.last_active[chat_id]
            logger.info("Session expired and removed for chat: %s", chat_id)

    async def discard_chat(self, chat_id: str) -> None:
        """Drop the live Copilot session for a chat so it can be rebuilt from DB state."""
        session = self.sessions.pop(chat_id, None)
        self.last_active.pop(chat_id, None)

        if session is None:
            return

        try:
            await session.destroy()
        except Exception:
            logger.warning("Failed to destroy discarded session for chat %s", chat_id, exc_info=True)
