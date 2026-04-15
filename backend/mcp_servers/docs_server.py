"""
Tools:
  - list_documents:  List all available PDF documents in Azure Blob Storage.
  - fetch_document:  Fetch the full text content of a specific PDF document.
"""

import asyncio
import json
import logging

from fastmcp import FastMCP
from blob_storage import list_documents as _list_documents
from pdf_extractor import fetch_document as _fetch_document

logger = logging.getLogger(__name__)

mcp = FastMCP("blob_docs")


@mcp.tool
async def list_documents() -> str:
    """
    List alle tilgjengelige PDF-dokumenter i Azure Blob Storage.
    Kall dette verktøyet først for å se hvilke dokumenter som er tilgjengelige.
    """
    loop = asyncio.get_running_loop()
    docs = await loop.run_in_executor(None, _list_documents)
    return json.dumps(docs, ensure_ascii=False)


@mcp.tool
async def fetch_document(name: str) -> str:
    """
    Hent tekstinnholdet fra et spesifikt PDF-dokument i Azure Blob Storage.
    VIKTIG: Kall alltid list_documents først for å få det eksakte filnavnet.

    Args:
        name: Det eksakte filnavnet, f.eks. 'KU Landskap 16.12.25 (1).PDF'
    """
    if not name:
        return json.dumps({"error": "Mangler dokumentnavn."})
    try:
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _fetch_document, name)
        return json.dumps({"name": name, "content": text}, ensure_ascii=False)
    except Exception as exc:
        logger.exception("fetch_document failed name=%s", name)
        return json.dumps({"error": f"Kunne ikke hente dokumentet '{name}'."})


# Expose as ASGI app for mounting in server.py
docs_app = mcp.http_app(path="/mcp")
