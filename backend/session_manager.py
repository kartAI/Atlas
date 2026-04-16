import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, cast

from copilot import CopilotClient
from copilot.session import PermissionHandler, PermissionRequestResult
from copilot.generated.session_events import SessionEventType
from mcp_servers.map_server import get_and_clear_shapes
from usage_tracker import get_or_create_tracker, discard_tracker
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
    logger.warning("PERMISSION DENIED: args=%s kwargs=%s", _args, _kwargs)
    return PermissionRequestResult(kind="denied-by-rules")

def allow_all_permission_handler(*_args, **_kwargs):
    """Allow tool permission requests in demo mode when SDK helpers are unavailable."""
    logger.info("PERMISSION GRANTED: args=%s kwargs=%s", _args, _kwargs)
    return PermissionRequestResult(kind="approved")


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
        self._usage_unsubscribers: dict = {}

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
            permission_handler = cast(
                Callable[..., PermissionRequestResult],
                sdk_approve_all if callable(sdk_approve_all) else allow_all_permission_handler,
            )
        else:
            permission_handler = cast(
                Callable[..., PermissionRequestResult],
                sdk_reject_all if callable(sdk_reject_all) else strict_permission_handler,
            )

        system_content = SYSTEM_PROMPT
        if prior_messages:
            system_content = SYSTEM_PROMPT + self._build_history_context(prior_messages)

        session = await self.client.create_session(
            model=MODEL_NAME,
            system_message={
                "mode": "append",
                "content": system_content,
            },
            streaming=True,
            reasoning_effort="high",
            # MCP servers the orchestrator can invoke.
            mcp_servers={
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
                "search": {
                    "type": "http",
                    "url": f"{SERVER_BASE_URL}/mcp/search/mcp",
                    "tools": ["*"],
                },
            },
            on_permission_request=permission_handler,
        )

        self.sessions[chat_id] = session
        self.last_active[chat_id] = datetime.now(timezone.utc)

        # Register usage tracker event handler for this session.
        tracker = get_or_create_tracker(chat_id)
        unsubscribe = session.on(tracker.handle_event)
        self._usage_unsubscribers[chat_id] = unsubscribe

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

    async def send_message(self, session, message: str, map_context=None, chat_id: str = "", tool_hints: list[str] | None = None) -> dict:
        """
        Send *message* to an active Copilot *session* and return a dict with
        the reply content and any pending map actions.

        If *tool_hints* is provided (list of validated MCP tool identifiers such as
        ``"vector-buffer"``), a directive block is prepended so the model
        prioritises those tools when answering.

        Callers are responsible for persisting messages to the database.
        """
        full_message = self._build_prompt(message, map_context, chat_id, tool_hints)

        # Refresh activity timestamp so cleanup_expired() doesn't reap the
        # session while a long send_and_wait() is in-flight.
        if chat_id and chat_id in self.last_active:
            self.last_active[chat_id] = datetime.now(timezone.utc)

        try:
            response = await session.send_and_wait(full_message, timeout=900)
        except Exception:
            # Evict the broken session so the next request creates a fresh one
            # instead of retrying against a permanently dead session.
            self._evict_session(chat_id)
            raise

        # Refresh again after the (potentially long) call completes.
        if chat_id and chat_id in self.last_active:
            self.last_active[chat_id] = datetime.now(timezone.utc)

        content = response.data.content
        map_actions = get_and_clear_shapes(chat_id)
        return {"content": content, "map_actions": map_actions}

    async def send_message_stream(self, session, message: str, map_context=None, chat_id: str = "", tool_hints: list[str] | None = None):
        """
        Async generator that yields SSE-style dicts as the model streams its
        response.  Yields three event types:

        - {"type": "thinking", "content": "..."} — reasoning delta chunks
        - {"type": "delta",    "content": "..."} — assistant message delta chunks
        - {"type": "done",     "content": "...", "map_actions": [...]} — final result

        Callers are responsible for persisting messages to the database.
        """
        full_message = self._build_prompt(message, map_context, chat_id, tool_hints)

        if chat_id and chat_id in self.last_active:
            self.last_active[chat_id] = datetime.now(timezone.utc)

        # Shared state accessed by the event handler
        queue: asyncio.Queue = asyncio.Queue()
        idle_event = asyncio.Event()
        error_holder: list = []
        full_content = []
        full_reasoning = []

        def handler(event):
            if event.type == SessionEventType.ASSISTANT_REASONING_DELTA:
                delta = getattr(event.data, "delta_content", None) or ""
                if delta:
                    full_reasoning.append(delta)
                    queue.put_nowait({"type": "thinking", "content": delta})
            elif event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                delta = getattr(event.data, "delta_content", None) or ""
                if delta:
                    full_content.append(delta)
                    queue.put_nowait({"type": "delta", "content": delta})
            elif event.type == SessionEventType.ASSISTANT_MESSAGE:
                # Full message (may contain the complete text if deltas were partial)
                content = getattr(event.data, "content", None) or ""
                if content and not full_content:
                    full_content.append(content)
            elif event.type == SessionEventType.SESSION_IDLE:
                idle_event.set()
            elif event.type == SessionEventType.SESSION_ERROR:
                error_holder.append(
                    Exception(f"Session error: {getattr(event.data, 'message', str(event.data))}")
                )
                idle_event.set()

        _STREAM_TIMEOUT = 900  # seconds — matches send_and_wait timeout

        unsubscribe = session.on(handler)
        try:
            await session.send(full_message)

            # Yield events as they arrive until the session goes idle.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + _STREAM_TIMEOUT
            while not idle_event.is_set():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError(f"Streaming timed out after {_STREAM_TIMEOUT}s")
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=min(1.0, remaining))
                    yield item
                except asyncio.TimeoutError:
                    continue

            # Drain any remaining items from the queue
            while not queue.empty():
                yield queue.get_nowait()

            if error_holder:
                raise error_holder[0]

        except Exception:
            self._evict_session(chat_id)
            raise
        finally:
            unsubscribe()

        if chat_id and chat_id in self.last_active:
            self.last_active[chat_id] = datetime.now(timezone.utc)

        content = "".join(full_content)
        map_actions = get_and_clear_shapes(chat_id)
        yield {"type": "done", "content": content, "map_actions": map_actions}

    def _build_prompt(self, message: str, map_context=None, chat_id: str = "", tool_hints: list[str] | None = None) -> str:
        """Build the full prompt string from user message and context."""
        parts = []
        if chat_id:
            parts.append(f"[SESSION_ID: {chat_id}]")

        if tool_hints:
            hint_list = "\n".join(f"- {tool_name}" for tool_name in tool_hints)
            parts.append(
                f"[TOOL HINTS]\n"
                f"The user has explicitly selected the following tools for this request:\n{hint_list}\n"
                f"You SHOULD use these tools when answering. Prioritise them over other tools.\n"
                f"[/TOOL HINTS]"
            )

        if map_context:
            layer_summary = "\n".join(
                f"- {l.get('name', 'Unnamed')} ({l.get('shape', '?')}): {json.dumps(l.get('geoJson'))}"
                for l in map_context
            )
            parts.append(f"[CURRENT MAP STATE]\n{layer_summary}")

        parts.append(f"[USER MESSAGE]\n{message}")
        return "\n\n".join(parts)

    def _evict_session(self, chat_id: str):
        """Evict a broken session so the next request creates a fresh one."""
        if chat_id and chat_id in self.sessions:
            self.sessions.pop(chat_id, None)
            self.last_active.pop(chat_id, None)
            unsub = self._usage_unsubscribers.pop(chat_id, None)
            if unsub:
                unsub()
            discard_tracker(chat_id)
            logger.warning(
                "Evicted broken session for chat %s; will recreate on next request",
                chat_id,
            )

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
            # Unsubscribe usage tracker and discard it.
            unsub = self._usage_unsubscribers.pop(chat_id, None)
            if unsub:
                unsub()
            discard_tracker(chat_id)
            del self.sessions[chat_id]
            del self.last_active[chat_id]
            logger.info("Session expired and removed for chat: %s", chat_id)

    async def discard_chat(self, chat_id: str) -> None:
        """Drop the live Copilot session for a chat so it can be rebuilt from DB state."""
        session = self.sessions.pop(chat_id, None)
        self.last_active.pop(chat_id, None)

        # Clean up usage tracker subscription.
        unsub = self._usage_unsubscribers.pop(chat_id, None)
        if unsub:
            unsub()
        discard_tracker(chat_id)

        if session is None:
            return

        try:
            await session.destroy()
        except Exception:
            logger.warning("Failed to destroy discarded session for chat %s", chat_id, exc_info=True)
