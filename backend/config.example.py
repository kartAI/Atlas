import os
from dotenv import load_dotenv
from azure.storage.blob import BlobServiceClient
import fitz

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

# Function to list documents in Azure Blob Storage

# def list_documents():
#   blob_service = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
#    container = blob_service.get_container_client(BLOB_CONTAINER_NAME)
#    return [blob.name for blob in container.list_blobs() if blob.name.endswith(".pdf") or blob.name.endswith(".PDF")]

# def fetch_document(blob_name):
#    blob_service = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
#    container = blob_service.get_container_client(BLOB_CONTAINER_NAME)
#    blob_data = container.download_blob(blob_name).readall()
#    doc = fitz.open(stream=blob_data, filetype="pdf")
#    text = ""
#    for page in doc:
#        text += page.get_text()
#    doc.close()
#    return text


# POSTGRESQL DATABASE URL
DATABASE_URL = os.getenv("DATABASE_URL")
