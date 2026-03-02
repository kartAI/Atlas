import asyncio
from backend.config import ALLOWED_ORIGINS
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from copilot import CopilotClient
from session_manager import SessionManager

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS, # Frontend port.
    allow_methods=["*"],
    allow_headers=["*"],
)

client = CopilotClient()
manager = SessionManager(client) # Creates a manager that lives for the entire server lifetime.
class ChatRequest(BaseModel):
    message: str # Prompt.
    session_id: str | None = None 
    # session_id is optional and can be None if not provided.
    # This allows the get_or_create method in SessionManager to handle both cases where session_id is given and where it is not.
    # If session_id is None, get_or_create will create a new session. If session_id is given, get_or_create will try to retrieve the existing session.
    
@app.on_event("startup")
async def startup_event(): 
    await client.start() 
@app.on_event("shutdown")
async def shutdown_event():
    await client.stop() 
    
@app.post("/api/chat")
async def chat(request: ChatRequest):
    session_id, session = await manager.get_or_create(request.session_id) 
    reply = await manager.send_message(session_id, request.message)
    return {"reply": reply, "session_id": session_id} # Now uses manager.get_or_create and manager.send_message instead of creating a session every time.

@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    history = manager.get_history(session_id)
    return {"history": history}    # New endpoint so the frontend can fetch the full conversation history for a given session_id.