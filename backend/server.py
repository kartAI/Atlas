from contextlib import asynccontextmanager
from config import ALLOWED_ORIGINS, DEMO_MODE, HOST, PORT
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from copilot import CopilotClient
from session_manager import SessionManager
from db import init_db_pool, close_pool, query
from config import list_documents, fetch_document # Demo functionality

client = CopilotClient()
manager = SessionManager(client)

@asynccontextmanager
async def lifespan(app):
     await client.start() # Starts the Copilot client when the server starts.
     await init_db_pool() # Connects to the database when the server starts.
     yield
     await client.stop() # Stops the Copilot client when the server shuts down.
     await close_pool() # Disconnects from the database when the server shuts down.   

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS, # Frontend port.
    allow_credentials=True, # Allows cookies to be sent in cross-origin requests, which is necessary for seesion managment.
    allow_methods=["*"],
    allow_headers=["*"],
)


# Document is optional. Frontend can include name of document to fetch in the prompt.
# Session_id is optional and can be None if not provided.
# This allows the get_or_create method in session_manager to handle both cases where session_id is given and where it is not.
# If session_id is None, get_or_create will create a new session. If session_id is given, get_or_create will try to retrieve the existing session.
class ChatRequest(BaseModel):
    message: str # Prompt.
    session_id: str | None = None 
    document: str | None = None

    
@app.post("/api/chat")
async def chat(request: ChatRequest):
    
    session_id, session = await manager.get_or_create(request.session_id) 
    
    print("DOCUMENT REQUESTED:", request.document) # Print the requested document name for debugging
    
    # DEMO FUNCTIONALITY TO FETCH DOCUMENTS FROM AZURE BLOB STORAGE
    docs = list_documents()
    print("ALL DOCUMENTS:", docs)

    # If the user is asking about available documents, list them clearly. Demo.
    if "dokument" in request.message.lower() and (
        "hvilke" in request.message.lower()
        or "liste" in request.message.lower()
        or "tilgang" in request.message.lower()
    ):
        prompt = f"""
Du har tilgang til følgende dokumenter i Azure Blob Storage:

{docs}

Presenter listen tydelig for brukeren.
"""
        reply = await manager.send_message(session_id, prompt)
        return {"reply": reply, "session_id": session_id}


    # FIND RELEVANT DOCUMENTS BASED ON KEYWORDS
    relevant_docs = docs
    
    print("RELEVANT DOCUMENTS:", relevant_docs)
    prompt = request.message

    # IF A SPECIFIC DOCUMENT IS REQUESTED, PRIORITIZE THAT ONE
    if request.document and "dokument" not in request.message.lower():
        relevant_docs = [request.document]
        
    # GET TEXT FROM THE MOST RELEVANT DOCUMENTS AND INCLUDE IN THE PROMPT
    if relevant_docs:
        combined_text = ""
        for doc in relevant_docs: # Splice to only include a set number of documents.
            print("USING DOCUMENT:", doc)
            doc_text = fetch_document(doc)
            combined_text += f"""
Dokumentnavn: {doc}
{doc_text}
-------------------------
"""

    prompt = f"""
Du har tilgang til følgende dokumenter fra Azure Blob Storage.

{combined_text}

Svar på brukerens spørsmål basert på informasjonen i dokumentene.

Spørsmål: {request.message}
"""
    # DEMO END

    reply = await manager.send_message(session_id, prompt)
    return {
        "reply": reply,
        "session_id": session_id
    } # Now uses manager.get_or_create and manager.send_message instead of creating a session every time.

# DEMO FUNCTIONALITY TO LIST DOCUMENTS IN AZURE BLOB STORAGE.
@app.get("/api/documents")
async def get_documents():
    docs = list_documents()
    return {"documents": docs} # New endpoint to list available documents in Azure Blob Storage.
# DEMO END.

@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    history = manager.get_history(session_id)
    return {"history": history}    # New endpoint so the frontend can fetch the full conversation history for a given session_id.

# TESTING DATABASE CONNECTIVITY AND QUERY EXECUTION
@app.get("/api/test-db")
async def test_db():
    if not DEMO_MODE:
        return {"error": "This endpoint is only available in demo mode."}
    result = await query("SELECT * FROM kulturmiljoer.kommunenummer LIMIT 5")
    return {"data": result} # Endpoint to test database connection and query execution.
# TESTING END

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=HOST, port=PORT, reload=True)