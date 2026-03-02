import asyncio
import uuid
from datetime import datetime, timedelta
from copilot import CopilotClient

class SessionManager:
    def __init__(self, client: CopilotClient, timeout_minutes=15):
        self.client = client
        
        # There are 3 different dictionaries here, to keep track of different aspects of the sessions.
        
        self.sessions = {} # this is for the session objects, not for the session IDs
        self.last_active = {} # this is for keeping track of when each session was last active
        self.history = {} # this is for keeping history for each session, so we / the user can see what has been sent previously
        
        self.timeout = timedelta(minutes=timeout_minutes) # this is how long a session should be active before it expires. Set to 15 by default, but can be adjusted on line 7

    async def get_or_create(self, session_id=None):
        # First checks if session_id is provided and exists in one of the session_id dicts - i.e. two checks in one. Used to retrieve an existing session if it exists.
        if session_id and session_id in self.sessions:
            self.last_active[session_id] = datetime.now() # updates the last active time for the session
        
        # If session_id is not provided or not found, a new session is created. Uses uuid to generate a unique session_id, then creates a new session with client.create_session. The new session is stored in the sessions dict and last active time is set to now.
        session_id = str(uuid.uuid4())
        session = await self.client.create_session({"model": "claude-sonnet-4.6"}) # Using sonnet for now. This can be changed or rerouted to another endpoint later I think.
        self.sessions[session_id] = session
        self.last_active[session_id] = datetime.now()
        self.history[session_id] = [] # initializes an empty history for the new session
        return session_id, session
    
    async def send_message(self, session_id, message):
        session = self.sessions [session_id]
        self.last_active[session_id] = datetime.now() # updates the last active time for the session
        self.history[session_id].append({"role": "user", "content": message}) # adds the message to the session history
        
        response = await session.send_and_wait({"prompt": message})
        content = response.data.content
        self.history[session_id].append({"role": "assistant", "content": content}) # adds the response to the session history
        return content
    
    async def cleanup_expired(self):
        now = datetime.now()
        expired = [
            session_id for session_id, last in self.last_active.items() if now - last > self.timeout
        ] # calculates how long it has been since each session was last active, and builds a list of those that have been inactive longer than the timeout period. now - last = time difference between now and last activity.
        
        for session_id in expired:
            await self.sessions[session_id].destroy() # destroys the session in Copilot
            del self.sessions[session_id] # removes the session from the sessions dict
            del self.last_active[session_id] # removes the session from the last_active dict
            del self.history[session_id] # removes the session from the history dict
            
        # Important: the expired sessions must be collected outside the loop in a separate list and deleted in their own loop. Moving it into the first loop will cause a RuntimeError.
        
    def get_history(self, session_id):
        return self.history.get(session_id, [])