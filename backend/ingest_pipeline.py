"""
Ingest pipeline for PDF documents from Azure Blob Storage.

Pipeline steps per document:
  1. discover_documents()       — list blobs with metadata from Azure
  2. should_reindex_document()  — skip if unchanged and already indexed
  3. extract_text()             — fetch PDF and extract text (blocking → thread)
  4. chunk_text()               — split into chunks (ready for embeddings later)
  5. generate_embeddings()      — GitHub Models API (text-embedding-3-small)
  6. save_indexed_document()    — upsert into documents table, status=ready
  7. update_index_status()      — set status (used on failure)

Entry points:
  run_pipeline(force, retry_failed)  — process all blobs, with concurrency control
  process_document(blob)             — process a single blob dict
"""

import asyncio
import logging
import time
from typing import Optional

from db import query, execute
from config import (
    fetch_document as _fetch_document_sync,
    list_documents_with_metadata as _list_docs_meta_sync,
)

logger = logging.getLogger(__name__)

# Max number of documents processed in parallel
_CONCURRENCY = 3


# ---------------------------------------------------------------------------
# Step 1: Discover documents
# ---------------------------------------------------------------------------

async def discover_documents() -> list[dict]:
    """
    List all PDFs in Blob Storage with name, last_modified, and file_hash (etag).
    Returns a list of dicts — does not write to the database.
    """
    loop = asyncio.get_running_loop()
    blobs = await loop.run_in_executor(None, _list_docs_meta_sync)
    logger.info("discover_documents: found %d PDFs in Blob Storage", len(blobs))
    return blobs


# ---------------------------------------------------------------------------
# Step 2: Decide whether to reindex
# ---------------------------------------------------------------------------

async def should_reindex_document(
    blob_name: str,
    last_modified: str,
    file_hash: str,
    retry_failed: bool = True,
) -> bool:
    """
    Returns True if the document should be (re)indexed.

    Skips if status=ready and neither last_modified nor file_hash has changed.
    Skips if status=processing (already running — avoids duplicate runs).
    Retries if status=failed and retry_failed=True.
    """
    rows = await query(
        "SELECT indexing_status, last_modified, file_hash FROM documents WHERE source_blob = %(b)s",
        {"b": blob_name},
    )

    if not rows:
        return True  # new document, not seen before

    doc = dict(rows[0])
    status = doc["indexing_status"]

    if status == "processing":
        logger.info("should_reindex: '%s' already processing — skipping", blob_name)
        return False

    if status == "ready":
        # Only re-index if something actually changed
        stored_lm = str(doc.get("last_modified") or "")
        stored_hash = doc.get("file_hash") or ""
        changed = stored_lm != str(last_modified) or stored_hash != file_hash
        return changed

    if status == "failed":
        return retry_failed

    # status = 'new' or unexpected value → process it
    return True


# ---------------------------------------------------------------------------
# Step 3: Extract text
# ---------------------------------------------------------------------------

async def extract_text(blob_name: str) -> str:
    """
    Fetch the PDF from Blob Storage and extract its full text.
    Runs in a thread executor since fitz PDF parsing is blocking.
    """
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    text = await loop.run_in_executor(None, _fetch_document_sync, blob_name)
    elapsed = time.perf_counter() - t0
    logger.info("extract_text: '%s' — %.2fs, %d chars", blob_name, elapsed, len(text))
    return text


# ---------------------------------------------------------------------------
# Step 4: Chunk text
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """
    Split text into overlapping chunks of chunk_size characters.
    overlap keeps context from bleeding off at chunk boundaries.

    Currently used for logging and future embedding support.
    Chunks are NOT stored as separate rows yet — that requires a schema change.
    """
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Step 5: Generate embeddings (GitHub Models API)
# ---------------------------------------------------------------------------

async def generate_embeddings(chunks: list[str]) -> list[float] | None:
    """
    Generate a single embedding vector for the document.

    Sends all chunks to the GitHub Models API (text-embedding-3-small),
    then averages the returned vectors into one 1536-dim embedding.
    Returns None if the token is not configured (safe fallback).
    """
    if not chunks:
        return None

    try:
        from embedding_client import get_embeddings
        vectors = await get_embeddings(chunks)
    except ValueError as e:
        logger.warning("generate_embeddings: %s", e)
        return None
    except Exception as e:
        logger.error("generate_embeddings: API call failed: %s", e)
        return None

    if not vectors:
        return None

    # Average all chunk embeddings into one document embedding
    dims = len(vectors[0])
    averaged = [0.0] * dims
    for vec in vectors:
        for i in range(dims):
            averaged[i] += vec[i]
    for i in range(dims):
        averaged[i] /= len(vectors)

    logger.info("generate_embeddings: %d chunks → 1 averaged vector (%d dims)", len(chunks), dims)
    return averaged


# ---------------------------------------------------------------------------
# Step 6: Save to database
# ---------------------------------------------------------------------------

async def save_indexed_document(
    blob_name: str,
    title: str,
    content: str,
    last_modified: str,
    file_hash: str,
    embeddings: list[float] | None = None,
) -> int:
    """
    Upsert the document into the database with status=ready.
    Stores the embedding vector if provided (otherwise NULL).
    Returns the document id.
    """
    t0 = time.perf_counter()

    # Convert embedding list to pgvector string format: "[0.1,0.2,...]"
    emb_str = str(embeddings) if embeddings else None

    rows = await query(
        """
        INSERT INTO documents
            (title, content, source_blob, last_modified, file_hash,
             embedding, indexing_status, indexed_at)
        VALUES
            (%(title)s, %(content)s, %(blob)s, %(lm)s, %(hash)s,
             %(emb)s::vector, 'ready', now())
        ON CONFLICT (source_blob) DO UPDATE SET
            title           = EXCLUDED.title,
            content         = EXCLUDED.content,
            last_modified   = EXCLUDED.last_modified,
            file_hash       = EXCLUDED.file_hash,
            embedding       = EXCLUDED.embedding,
            indexing_status = 'ready',
            indexed_at      = now(),
            error_message   = NULL
        RETURNING id;
        """,
        {"title": title, "content": content, "blob": blob_name,
         "lm": last_modified, "hash": file_hash, "emb": emb_str},
    )
    elapsed = time.perf_counter() - t0
    doc_id = rows[0]["id"] if rows else None
    logger.info("save_indexed_document: '%s' → id=%s, embedding=%s (%.2fs)",
                blob_name, doc_id, "yes" if embeddings else "no", elapsed)
    return doc_id


# ---------------------------------------------------------------------------
# Step 7: Update index status
# ---------------------------------------------------------------------------

async def update_index_status(blob_name: str, status: str, error: Optional[str] = None) -> None:
    """Set indexing_status (and optionally error_message) for a document row."""
    await execute(
        """
        UPDATE documents
        SET indexing_status = %(status)s,
            error_message   = %(error)s
        WHERE source_blob = %(blob)s
        """,
        {"status": status, "blob": blob_name, "error": error},
    )


# ---------------------------------------------------------------------------
# Full pipeline for one document
# ---------------------------------------------------------------------------

async def process_document(blob: dict, retry_failed: bool = True) -> dict:
    """
    Run all pipeline steps for a single blob dict (name, last_modified, file_hash).
    Returns a result dict: status in ('ok', 'skipped', 'error').
    """
    blob_name = blob["name"]
    last_modified = blob["last_modified"]
    file_hash = blob["file_hash"]

    # Step 2: check if (re)indexing is needed
    if not await should_reindex_document(blob_name, last_modified, file_hash, retry_failed):
        logger.info("process_document: skipping '%s' (up to date)", blob_name)
        return {"status": "skipped", "blob": blob_name}

    # Lock the row as 'processing' before starting (prevents duplicate runs)
    await execute(
        """
        INSERT INTO documents
            (title, content, source_blob, last_modified, file_hash, indexing_status)
        VALUES (%(blob)s, '', %(blob)s, %(lm)s, %(hash)s, 'processing')
        ON CONFLICT (source_blob) DO UPDATE SET indexing_status = 'processing'
        """,
        {"blob": blob_name, "lm": last_modified, "hash": file_hash},
    )

    try:
        # Step 3: extract text
        content = await extract_text(blob_name)

        # Step 4: chunk (for logging and future embedding support)
        t0 = time.perf_counter()
        chunks = chunk_text(content)
        logger.info("chunk_text: '%s' → %d chunks (%.3fs)", blob_name, len(chunks), time.perf_counter() - t0)

        # Step 5: generate embeddings
        t0 = time.perf_counter()
        embeddings = await generate_embeddings(chunks)
        logger.info("generate_embeddings: '%s' → done (%.3fs)", blob_name, time.perf_counter() - t0)

        # Step 6: save
        title = blob_name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        doc_id = await save_indexed_document(
            blob_name=blob_name,
            title=title,
            content=content,
            last_modified=last_modified,
            file_hash=file_hash,
            embeddings=embeddings,
        )

        return {"status": "ok", "blob": blob_name, "document_id": doc_id}

    except Exception as e:
        logger.error("process_document: failed '%s': %s", blob_name, e, exc_info=True)
        await update_index_status(blob_name, "failed", error=str(e))
        return {"status": "error", "blob": blob_name, "error": str(e)}


# ---------------------------------------------------------------------------
# Run pipeline for all documents
# ---------------------------------------------------------------------------

async def run_pipeline(force: bool = False, retry_failed: bool = True) -> dict:
    """
    Discover all PDFs in Blob Storage and process those that need (re)indexing.

    Args:
        force:        Reindex everything, even unchanged documents.
        retry_failed: Retry documents with status=failed.

    Returns a summary dict with counts and timing.
    """
    t_total = time.perf_counter()

    # Step 1: discover
    blobs = await discover_documents()
    if not blobs:
        return {"status": "ok", "total": 0, "message": "No documents found in Blob Storage."}

    if force:
        # Reset all to 'new' so every document gets reprocessed
        for i, blob in enumerate(blobs):
            await execute(
                "UPDATE documents SET indexing_status = 'new' WHERE source_blob = %(b)s",
                {"b": blob["name"]},
            )
            logger.info("run_pipeline: force-reset %d/%d — %s", i + 1, len(blobs), blob["name"])

    # Process with bounded concurrency (avoids hammering DB and Blob Storage)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def process_with_limit(blob):
        async with semaphore:
            return await process_document(blob, retry_failed=retry_failed)

    results = await asyncio.gather(*[process_with_limit(blob) for blob in blobs])

    ok      = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed  = [r for r in results if r["status"] == "error"]

    elapsed = time.perf_counter() - t_total
    logger.info(
        "run_pipeline: done in %.2fs — %d indexed, %d skipped, %d failed",
        elapsed, len(ok), len(skipped), len(failed),
    )

    return {
        "status": "ok",
        "total": len(blobs),
        "indexed": len(ok),
        "skipped": len(skipped),
        "failed": len(failed),
        "elapsed_seconds": round(elapsed, 2),
        "failed_files": [{"blob": r["blob"], "error": r.get("error")} for r in failed],
    }
