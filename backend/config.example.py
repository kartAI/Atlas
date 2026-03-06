import os
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
import fitz

load_dotenv()

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# CORS Middleware configuration
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# AI Model configuration
MODEL_NAME = os.getenv("MODEL_NAME", "your-model-name-here")

# Session management configuration
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "15"))

# System prompt configuration - define the behavior of the AI assistant
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", """
Your system prompt here.
""".strip())

# Azure Blob Storage configuration
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
BLOB_CONTAINER_NAME = os.getenv("BLOB_CONTAINER_NAME")

# POSTGRESQL DATABASE URL
DATABASE_URL = os.getenv("DATABASE_URL")
