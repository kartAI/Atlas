import asyncio
import os
import uuid
from datetime import datetime, timedelta
from copilot import CopilotClient, PermissionHandler
from config import DEMO_MODE, MODEL_NAME, SYSTEM_PROMPT, SESSION_TIMEOUT_MINUTES, REASONING_EFFORT

SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000")


def strict_permission_handler(*_args, **_kwargs):
    """Deny tool permission requests by default outside demo mode."""
    return False


class SessionManager:
    def __init__(self, client: CopilotClient, timeout_minutes=SESSION_TIMEOUT_MINUTES):
        self.client = client
        self.sessions = {}
        self.last_active = {}
        self.history = {}
        self.token_usage = {}
        self.timeout = timedelta(minutes=timeout_minutes)

    async def get_or_create(self, session_id=None):
        if session_id and session_id in self.sessions:
            self.last_active[session_id] = datetime.now()
            return session_id, self.sessions[session_id]

        session_id = str(uuid.uuid4())
        permission_handler = (
            PermissionHandler.approve_all
            if DEMO_MODE
            else getattr(PermissionHandler, "reject_all", strict_permission_handler)
        )

        session = await self.client.create_session({
            "model": MODEL_NAME,
            "reasoning_effort": REASONING_EFFORT,
            "system_message": {
                "mode": "append",
                "content": SYSTEM_PROMPT
            },
           
            # The orchestrator (Copilot) can now pick from three specialised servers:
            #   - db:   raw SQL tools for exploring and querying the database
            #   - geo_server:  domain-specific geo/KU tools (buffer search, kommuner etc.) 
            #   - docs_server: Azure Blob document tools (list + fetch PDFs)
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
            },
            "on_permission_request": permission_handler,
        })

        self.sessions[session_id] = session
        self.last_active[session_id] = datetime.now()
        self.history[session_id] = []
        self.token_usage[session_id] = {"input": 0, "output": 0, "premium_requests": 0, "total": 0}
        return session_id, session

    async def send_message(self, session_id, message):
        session = self.sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session {session_id} not found or expired")
        self.last_active[session_id] = datetime.now()
        self.history[session_id].append({"role": "user", "content": message})
        response = await session.send_and_wait({"prompt": message}, timeout=180)
    
        self.token_usage[session_id]["input"] += response.data.input_tokens or 0
        self.token_usage[session_id]["output"] += response.data.output_tokens or 0
        self.token_usage[session_id]["premium_requests"] += response.data.total_premium_requests or 0
        print(f"Session tokens — in: {self.token_usage[session_id]['input']} out: {self.token_usage[session_id]['output']} premium: {self.token_usage[session_id]['premium_requests']}")
    
        content = response.data.content
        self.history[session_id].append({"role": "assistant", "content": content})
        return content

    async def cleanup_expired(self):
        now = datetime.now()
        expired = [
            sid for sid, last in self.last_active.items()
            if now - last > self.timeout
        ]
        for sid in expired:
            await self.sessions[sid].destroy()
            del self.sessions[sid]
            del self.last_active[sid]
            del self.history[sid]
            del self.token_usage[sid]

    def get_history(self, session_id):
        return self.history.get(session_id, [])