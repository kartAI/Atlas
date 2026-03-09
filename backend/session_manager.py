import asyncio
import uuid
from datetime import datetime, timedelta
from copilot import CopilotClient, PermissionHandler
from config import DEMO_MODE, MODEL_NAME, SYSTEM_PROMPT, SESSION_TIMEOUT_MINUTES
from tools import list_kommuner_tool, list_vernetyper_tool, buffer_search_tool # Demo functionality to list municipalities and protection types from the database. Can be used in the system prompt to make it available for the model to call.


def strict_permission_handler(*_args, **_kwargs):
    """Deny tool permission requests by default outside demo mode."""
    return False

class SessionManager:
    def __init__(self, client: CopilotClient, timeout_minutes=SESSION_TIMEOUT_MINUTES):
        self.client = client
        
        # There are 3 different dictionaries here, to keep track of different aspects of the sessions.
        
        self.sessions = {} # Session objects. Not session IDs.
        self.last_active = {} # Tracking when last active for each session.
        self.history = {} # History for each session.
        
        self.timeout = timedelta(minutes=timeout_minutes) # How long a session is before it expires. Can be adjusted in config.py.

    # First checks if session_id is provided and exists in one of the session_id dicts. 
    # Used to retrieve an existing session if it exists.
    async def get_or_create(self, session_id=None):
        
        if session_id and session_id in self.sessions:
            self.last_active[session_id] = datetime.now() # Updates the last active time for the session
            return session_id, self.sessions[session_id]
       
        
        
        # If session_id is missing or invalid, create a new session using a UUID.
        # Store it in sessions and set last_active to the current time.
        # The session is created with the specified model, system prompt, and tools.
        session_id = str(uuid.uuid4())
        # WARNING: approve_all must only be used for local/demo workflows.
        permission_handler = (
            PermissionHandler.approve_all
            if DEMO_MODE
            else getattr(PermissionHandler, "reject_all", strict_permission_handler)
        )
        session = await self.client.create_session({
            "model": MODEL_NAME,
            "system_message": {
                "mode": "append",
                "content": SYSTEM_PROMPT
            },
            "tools": [list_kommuner_tool, list_vernetyper_tool, buffer_search_tool], # Adds the tools to the session, making them available for the model to call.
            "on_permission_request": permission_handler # In non-demo mode this denies by default; replace with allowlist/manual approval as needed.
        })
        self.sessions[session_id] = session
        self.last_active[session_id] = datetime.now()
        self.history[session_id] = [] # Initializes an empty history for the new session.
        return session_id, session
    
    async def send_message(self, session_id, message):
        session = self.sessions [session_id]
        self.last_active[session_id] = datetime.now() # Updates the last active time for the session.
        self.history[session_id].append({"role": "user", "content": message}) # Adds the message to the session history.
        
        response = await session.send_and_wait({"prompt": message})
        content = response.data.content
        self.history[session_id].append({"role": "assistant", "content": content}) # Adds the response to the session history.
        return content
    
    # Calculates time since last activity for each session.
    # Marks sessions inactive if (now - last_active) exceed the timeout.
    async def cleanup_expired(self):
        now = datetime.now()
        expired = [
            session_id for session_id, last in self.last_active.items() if now - last > self.timeout
        ] 
        
        
        for session_id in expired:
            await self.sessions[session_id].destroy() # Destroys the session in Copilot.
            del self.sessions[session_id] # Removes the session from the sessions dict.
            del self.last_active[session_id] # Removes the session from the last_active dict.
            del self.history[session_id] # Removes the session from the history dict.
            
        # Important: the expired sessions must be collected outside the loop in a separate list and deleted in their own loop. 
        # Moving it into the first loop will cause a RuntimeError.
        
    def get_history(self, session_id):
        return self.history.get(session_id, [])