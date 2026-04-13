import os
from dotenv import load_dotenv

load_dotenv()

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# CORS Middleware configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") # Placeholder URL for frontend.

# AI Model configuration
MODEL_NAME = os.getenv("MODEL_NAME", "your-model-name-here")

# Session management configuration
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "15"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "100"))
MAX_HISTORY_PER_SESSION = int(os.getenv("MAX_HISTORY_PER_SESSION", "200"))
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes", "on")

# Buffer search hardening
BUFFER_DISTANCE_MIN_METERS = int(os.getenv("BUFFER_DISTANCE_MIN_METERS", "10"))
BUFFER_DISTANCE_MAX_METERS = int(os.getenv("BUFFER_DISTANCE_MAX_METERS", "50000"))
BUFFER_RESULT_LIMIT = int(os.getenv("BUFFER_RESULT_LIMIT", "200"))

# System prompt configuration - define the behavior of the AI assistant
SYSTEM_PROMPT = """
Your system prompt here.
""".strip()

# Azure Blob Storage configuration
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME")


# POSTGRESQL DATABASE URL
DATABASE_URL = os.getenv("DATABASE_URL")

# Search / indexing
# INDEXING_ENABLED=true  — enable index_document and index_all_documents MCP tools
# GITHUB_MODELS_TOKEN=ghp_...  — GitHub fine-grained token with 'models:read' scope (for semantic search)
