"""
MCP Server: Document Search

Tools:
  - search_documents:         Full-text search across documents (Norwegian tsvector).
  - search_documents_fuzzy:   Fuzzy search (pg_trgm trigram similarity).
  - search_documents_semantic: Semantic search (pgvector cosine similarity).
  - search_hybrid:            Combined full-text + semantic + fuzzy search.
  - index_document:           Index a single PDF from Azure Blob Storage (via pipeline).
  - index_all_documents:      Index all PDFs from Azure Blob Storage (via pipeline).
  - get_indexing_status:       Show indexing status counts per category.
"""

import json
import logging
import os

from fastmcp import FastMCP
from search_service import search_full_text, search_fuzzy, search_semantic, hybrid_search
from ingest_pipeline import process_document, run_pipeline, discover_documents, update_index_status
from db import query as db_query

logger = logging.getLogger(__name__)

mcp = FastMCP("search_server")

# Indexing tools are disabled unless explicitly enabled via env var.
# This prevents unintended writes and external API spend on unprotected deployments.
_INDEXING_ENABLED = os.getenv("INDEXING_ENABLED", "").lower() in ("1", "true", "yes")


@mcp.tool(annotations={"readOnlyHint": True})
async def search_documents(query: str, limit: int = 10) -> str:
    """
    Søk i dokumenter med norsk fulltekstsøk.
    Returnerer dokumenter rangert etter relevans.

    Args:
        query: Søkeord eller frase, f.eks. 'konsekvensutredning landskap'.
        limit: Maks antall resultater (standard 10).
    """
    if not query or not query.strip():
        return json.dumps({"error": "Søkeord mangler."})

    try:
        results = await search_full_text(query, limit)
        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("search_documents failed")
        return json.dumps({"error": f"Søk feilet: {e}"})


@mcp.tool(annotations={"readOnlyHint": True})
async def search_documents_fuzzy(query: str, limit: int = 10) -> str:
    """
    Fuzzy-søk i dokumenter (pg_trgm trigram-likhet).
    Brukes når fulltekstsøk ikke gir treff og du vil prøve bredere matching.

    Args:
        query: Søkeord eller del av ord, f.eks. 'kulturminne'.
        limit: Maks antall resultater (standard 10).
    """
    if not query or not query.strip():
        return json.dumps({"error": "Søkeord mangler."})

    try:
        results = await search_fuzzy(query, limit)
        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("search_documents_fuzzy failed")
        return json.dumps({"error": f"Fuzzy-søk feilet: {e}"})


@mcp.tool(annotations={"readOnlyHint": True})
async def search_documents_semantic(query: str, limit: int = 10) -> str:
    """
    Semantisk søk i dokumenter via pgvector (cosine similarity).
    Bruker embedding-modellen til å finne dokumenter med lignende innhold,
    selv om ordene ikke matcher direkte. Krever at GITHUB_MODELS_TOKEN er satt.

    Args:
        query: Søkeord eller frase, f.eks. 'miljøpåvirkning av veier'.
        limit: Maks antall resultater (standard 10).
    """
    if not query or not query.strip():
        return json.dumps({"error": "Søkeord mangler."})

    try:
        results = await search_semantic(query, limit)
        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("search_documents_semantic failed")
        return json.dumps({"error": f"Semantisk søk feilet: {e}"})


@mcp.tool(annotations={"readOnlyHint": True})
async def search_hybrid(query: str, limit: int = 10) -> str:
    """
    Kombinert søk: fulltekst + semantisk + fuzzy.
    Gir bredest mulig dekning ved å slå sammen resultater fra flere søkemetoder.

    Args:
        query: Søkeord eller frase.
        limit: Maks antall resultater (standard 10).
    """
    if not query or not query.strip():
        return json.dumps({"error": "Søkeord mangler."})

    try:
        results = await hybrid_search(query, limit)
        return json.dumps({
            "count": len(results),
            "results": results,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("search_hybrid failed")
        return json.dumps({"error": f"Hybrid-søk feilet: {e}"})


@mcp.tool(annotations={"readOnlyHint": False})
async def index_document(blob_name: str, force: bool = False) -> str:
    """
    Hent én PDF fra Azure Blob Storage og indekser den via ingest-pipelinen.
    Hopper over filen hvis den allerede er indeksert og ikke har endret seg,
    med mindre force=True.

    Args:
        blob_name: Filnavn i Blob Storage, f.eks. 'KU Landskap 2025.PDF'.
        force:     Tving re-indeksering selv om filen er uendret.
    """
    if not blob_name or not blob_name.strip():
        return json.dumps({"error": "Filnavn mangler."})
    if not _INDEXING_ENABLED:
        return json.dumps({"error": "Indeksering er ikke aktivert. Sett INDEXING_ENABLED=true i miljøvariabler."})

    try:
        # Discover metadata for this specific blob
        all_blobs = await discover_documents()
        blob = next((b for b in all_blobs if b["name"] == blob_name.strip()), None)
        if blob is None:
            return json.dumps({"error": f"Fant ikke '{blob_name}' i Blob Storage."})

        if force:
            # Reset status so the atomic claim in process_document will reprocess it.
            await update_index_status(blob["name"], "new")

        result = await process_document(blob, retry_failed=True)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("index_document failed")
        return json.dumps({"error": f"Indeksering feilet: {e}"})


@mcp.tool(annotations={"readOnlyHint": False})
async def index_all_documents(force: bool = False) -> str:
    """
    Indekser alle PDF-filer fra Azure Blob Storage via ingest-pipelinen.
    Filer som allerede er indeksert og ikke har endret seg, hoppes over.
    Bruk force=True for å tvinge full re-indeksering av alle filer.

    Args:
        force: Reindekser alt selv om filene er uendret.
    """
    try:
        if not _INDEXING_ENABLED:
            return json.dumps({"error": "Indeksering er ikke aktivert. Sett INDEXING_ENABLED=true i miljøvariabler."})
        result = await run_pipeline(force=force, retry_failed=True)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.exception("index_all_documents failed")
        return json.dumps({"error": f"Masseindeksering feilet: {e}"})


@mcp.tool(annotations={"readOnlyHint": True})
async def get_indexing_status() -> str:
    """
    Vis statusoversikt for dokumentindeksering fra Azure Blob Storage.
    Returnerer antall PDF-filer per status: new, processing, ready, partial, failed.
    Teller bare dokumenter med source_blob (ekte PDF-er fra Blob Storage).
    """
    try:
        # Count only blob-sourced documents (source_blob IS NOT NULL)
        rows = await db_query(
            """
            SELECT indexing_status, COUNT(*) AS count
            FROM documents
            WHERE source_blob IS NOT NULL
            GROUP BY indexing_status
            ORDER BY indexing_status;
            """,
            {},
        )
        status_counts = {row["indexing_status"]: row["count"] for row in rows}
        total_blobs = sum(status_counts.values())

        # List failed documents with error messages
        failed_rows = await db_query(
            "SELECT source_blob, error_message FROM documents WHERE indexing_status = 'failed' AND source_blob IS NOT NULL;",
            {},
        )
        failed_details = [{"blob": r["source_blob"], "error": r["error_message"]} for r in failed_rows]

        return json.dumps({
            "total_pdf_files": total_blobs,
            "status_counts": status_counts,
            "failed_documents": failed_details,
        }, ensure_ascii=False, default=str)
    except Exception as e:
        logger.exception("get_indexing_status failed")
        return json.dumps({"error": f"Statussjekk feilet: {e}"})


# Expose as ASGI app for mounting in server.py
search_app = mcp.http_app(path="/mcp")
