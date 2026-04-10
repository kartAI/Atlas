"""
Ingest pipeline for PDF documents from Azure Blob Storage.

Pipeline steps per document:
  1. discover_documents()       — list blobs with metadata from Azure
  2. should_reindex_document()  — skip if unchanged and already indexed
  3. extract_blocks()           — fetch PDF and extract structured text blocks (blocking → thread)
  4. chunk_document()           — split into structure-aware chunks (heading-based, from chunker.py)
  5. save_indexed_document()    — upsert into documents table (content for full-text search)
  6. save_chunks()              — embed each chunk via GitHub Models API and insert into chunks table
  7. update_index_status()      — set final status

Status model (indexing_status):
  new        — not yet processed
  processing — pipeline is actively working on this document;
               stale rows (>30 min) are reclaimed at next pipeline start
  ready      — fully indexed: content + ALL chunk embeddings available
  partial    — content indexed (full-text/fuzzy OK), but some or all
               embeddings failed; automatically retried on next pipeline run
  failed     — extraction or processing error

Legacy functions kept for reference (no longer called in the main pipeline):
  extract_text()       — plain text extraction (still used by docs_server indirectly via config)
  chunk_text()         — fixed-size character chunking (superseded by chunker.py)
  generate_embeddings() — averaged document embedding (fallback for doc-level embedding)

Entry points:
  run_pipeline(force, retry_failed)  — process all blobs, with concurrency control
  process_document(blob)             — process a single blob dict
"""

import asyncio
import json
import logging
import time
from typing import Optional

from db import query, execute, get_connection
from config import (
    fetch_document as _fetch_document_sync,
    fetch_document_blocks as _fetch_document_blocks_sync,
    list_documents_with_metadata as _list_docs_meta_sync,
)

logger = logging.getLogger(__name__)

# Max number of documents processed in parallel
_CONCURRENCY = 3

# Documents stuck in 'processing' longer than this are considered stale
# (crashed/killed worker) and will be reclaimed on the next pipeline run.
_STALE_PROCESSING_MINUTES = 30


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

    # status = 'new', 'partial', or unexpected value → process it.
    # 'partial' means content was indexed but embeddings failed — always retry.
    return True


# ---------------------------------------------------------------------------
# Step 3: Extract text (legacy — kept for reference; not used in main pipeline)
# ---------------------------------------------------------------------------

async def extract_text(blob_name: str) -> str:
    """
    Fetch the PDF from Blob Storage and extract its full text.
    Runs in a thread executor since fitz PDF parsing is blocking.

    NOTE: Superseded by extract_blocks() in the main pipeline.
    Kept here because docs_server.py calls config.fetch_document() directly.
    """
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    text = await loop.run_in_executor(None, _fetch_document_sync, blob_name)
    elapsed = time.perf_counter() - t0
    logger.info("extract_text: '%s' — %.2fs, %d chars", blob_name, elapsed, len(text))
    return text


# ---------------------------------------------------------------------------
# Step 3 (new): Extract structured blocks
# ---------------------------------------------------------------------------

async def extract_blocks(blob_name: str) -> list[dict]:
    """
    Fetch the PDF from Blob Storage and extract structured text blocks with
    font metadata (text, page, font_size, is_bold, bbox).
    Runs in a thread executor since fitz PDF parsing is blocking.
    Used by the structure-aware chunking pipeline.
    """
    loop = asyncio.get_running_loop()
    t0 = time.perf_counter()
    blocks = await loop.run_in_executor(None, _fetch_document_blocks_sync, blob_name)
    elapsed = time.perf_counter() - t0
    total_chars = sum(len(b.get("text", "")) for b in blocks)
    logger.info(
        "extract_blocks: '%s' — %.2fs, %d blocks, %d chars",
        blob_name, elapsed, len(blocks), total_chars,
    )
    return blocks


# ---------------------------------------------------------------------------
# Step 4: Chunk text (legacy — fixed-size, superseded by chunk_document())
# ---------------------------------------------------------------------------

def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """
    Split text into overlapping fixed-size chunks.

    NOTE: Superseded by chunk_document() from chunker.py in the main pipeline.
    Kept here to avoid breaking any external references.
    """
    if not text:
        return []
    step = max(chunk_size - overlap, 1)
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += step
    return chunks


# ---------------------------------------------------------------------------
# Step 5: Generate embeddings (legacy — averaged doc vector, superseded)
# ---------------------------------------------------------------------------

async def generate_embeddings(chunks: list[str]) -> list[float] | None:
    """
    Generate a single averaged embedding vector for a document.

    NOTE: Superseded by per-chunk embedding in save_chunks() in the main pipeline.
    Kept here to avoid breaking any external references.
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
# Step 5: Save document row to database
# ---------------------------------------------------------------------------

async def save_indexed_document(
    blob_name: str,
    title: str,
    content: str,
    last_modified: str,
    file_hash: str,
    embeddings: list[float] | None = None,
    indexing_status: str = "ready",
) -> int:
    """
    Upsert the document into the database.
    Stores the embedding vector if provided (otherwise NULL).
    Returns the document id.

    The caller controls *indexing_status* so that the document can stay in
    'processing' while chunks are being written and only flip to 'ready'
    after all data is committed.
    """
    t0 = time.perf_counter()

    # Convert embedding list to pgvector string format: "[0.1,0.2,...]"
    emb_str = json.dumps(embeddings) if embeddings else None

    rows = await query(
        """
        INSERT INTO documents
            (title, content, source_blob, last_modified, file_hash,
             embedding, indexing_status, indexed_at)
        VALUES
            (%(title)s, %(content)s, %(blob)s, %(lm)s, %(hash)s,
             %(emb)s::vector, %(status)s, now())
        ON CONFLICT (source_blob) DO UPDATE SET
            title           = EXCLUDED.title,
            content         = EXCLUDED.content,
            last_modified   = EXCLUDED.last_modified,
            file_hash       = EXCLUDED.file_hash,
            embedding       = EXCLUDED.embedding,
            indexing_status = EXCLUDED.indexing_status,
            indexed_at      = now(),
            error_message   = NULL
        RETURNING id;
        """,
        {"title": title, "content": content, "blob": blob_name,
         "lm": last_modified, "hash": file_hash, "emb": emb_str,
         "status": indexing_status},
    )
    elapsed = time.perf_counter() - t0
    doc_id = rows[0]["id"] if rows else None
    logger.info("save_indexed_document: '%s' → id=%s, embedding=%s (%.2fs)",
                blob_name, doc_id, "yes" if embeddings else "no", elapsed)
    return doc_id


# ---------------------------------------------------------------------------
# Step 6: Save chunks with per-chunk embeddings
# ---------------------------------------------------------------------------

# Maximum number of chunk texts sent to the embeddings API in a single batch.
# Keeps individual API calls manageable for documents with many chunks.
_EMBEDDING_BATCH_SIZE = 50  # TUNE


async def save_chunks(document_id: int, chunks: list[dict]) -> tuple[int, int]:
    """
    Embed all chunks (batched API calls) and upsert them into the chunks table.

    Steps:
      1. Generate embeddings for all chunk texts in batches of _EMBEDDING_BATCH_SIZE.
      2. In a single transaction:
         a. DELETE existing chunks for this document (clean slate on re-index).
         b. INSERT parent chunks (local_parent_id = None), recording their DB IDs.
         c. INSERT child chunks, resolving local_parent_id → real DB id.

    Returns (total_inserted, embedded_count).
    Embedding failures are non-fatal: affected chunks are stored without a vector.
    """
    if not chunks:
        return (0, 0)

    # --- Step 1: generate embeddings in batches (outside transaction — external API) ---
    texts       = [c["text"] for c in chunks]
    all_vectors: list[list[float] | None] = []

    try:
        from embedding_client import get_embeddings
        for batch_start in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[batch_start:batch_start + _EMBEDDING_BATCH_SIZE]
            try:
                batch_vectors = await get_embeddings(batch)
                all_vectors.extend(batch_vectors)
            except Exception as e:
                logger.warning(
                    "save_chunks: embedding batch %d–%d failed for doc %s: %s",
                    batch_start, batch_start + len(batch) - 1, document_id, e,
                )
                all_vectors.extend([None] * len(batch))
    except ValueError as e:
        # GITHUB_MODELS_TOKEN not configured — store chunks without embeddings
        logger.warning("save_chunks: %s — storing chunks without embeddings", e)
        all_vectors = [None] * len(chunks)

    # Guard: ensure vector list length matches chunk list length
    if len(all_vectors) != len(chunks):
        logger.warning(
            "save_chunks: vector count mismatch (%d vectors for %d chunks) — padding with None",
            len(all_vectors), len(chunks),
        )
        all_vectors = (all_vectors + [None] * len(chunks))[:len(chunks)]

    embedded_count = sum(1 for v in all_vectors if v is not None)

    # Build a lookup: local_id → (chunk dict, embedding vector)
    local_id_map: dict[int, tuple[dict, list[float] | None]] = {
        c["local_id"]: (c, all_vectors[i])
        for i, c in enumerate(chunks)
    }

    parent_chunks = [c for c in chunks if c["local_parent_id"] is None]
    child_chunks  = [c for c in chunks if c["local_parent_id"] is not None]

    # --- Steps 2-4: DELETE + all INSERTs in a single transaction ---
    local_id_to_db_id: dict[int, int] = {}

    async with get_connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM chunks WHERE document_id = %(doc_id)s",
                    {"doc_id": document_id},
                )

                for chunk in parent_chunks:
                    db_id = await _insert_chunk(
                        cur, document_id, None, chunk,
                        local_id_map[chunk["local_id"]][1],
                    )
                    local_id_to_db_id[chunk["local_id"]] = db_id

                for chunk in child_chunks:
                    parent_db_id = local_id_to_db_id.get(chunk["local_parent_id"])
                    if parent_db_id is None:
                        raise RuntimeError(
                            f"save_chunks: parent local_id={chunk['local_parent_id']!r} "
                            f"not found in id map for doc {document_id} — "
                            "parent INSERT may have silently returned no row"
                        )
                    await _insert_chunk(
                        cur, document_id, parent_db_id, chunk,
                        local_id_map[chunk["local_id"]][1],
                    )

    total = len(parent_chunks) + len(child_chunks)
    logger.info(
        "save_chunks: document_id=%s → %d chunks saved (%d with embeddings)",
        document_id, total, embedded_count,
    )
    return (total, embedded_count)


async def _insert_chunk(
    cur,
    document_id:  int,
    parent_db_id: int | None,
    chunk:        dict,
    vector:       list[float] | None,
) -> int | None:
    """
    Insert a single chunk row into the chunks table using the given cursor.
    Returns the new DB id. Raises RuntimeError if the INSERT returns no row.
    """
    meta     = chunk["metadata"]
    emb_str  = json.dumps(vector) if vector else None

    await cur.execute(
        """
        INSERT INTO chunks (
            document_id, parent_chunk_id, chunk_index, text, char_count,
            file_type, heading_path, section_title, section_number,
            page_start, page_end, topic_type, alternative, delomrade,
            contains_table, embedding
        ) VALUES (
            %(doc_id)s, %(parent_id)s, %(idx)s, %(text)s, %(char_count)s,
            %(file_type)s, %(heading_path)s, %(section_title)s, %(section_number)s,
            %(page_start)s, %(page_end)s, %(topic_type)s, %(alternative)s, %(delomrade)s,
            %(contains_table)s, %(embedding)s::vector
        ) RETURNING id;
        """,
        {
            "doc_id":         document_id,
            "parent_id":      parent_db_id,
            "idx":            chunk["chunk_index"],
            "text":           chunk["text"],
            "char_count":     chunk["char_count"],
            "file_type":      meta.get("file_type"),
            "heading_path":   meta.get("heading_path"),
            "section_title":  meta.get("section_title"),
            "section_number": meta.get("section_number"),
            "page_start":     meta.get("page_start"),
            "page_end":       meta.get("page_end"),
            "topic_type":     meta.get("topic_type"),
            "alternative":    meta.get("alternative"),
            "delomrade":      meta.get("delomrade"),
            "contains_table": meta.get("contains_table", False),
            "embedding":      emb_str,
        },
    )
    row = await cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"_insert_chunk: INSERT returned no row for document_id={document_id} "
            f"chunk_index={chunk['chunk_index']} — unexpected empty RETURNING result"
        )
    return row["id"]


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

    # Atomic claim: check eligibility and set status='processing' in one statement.
    # Returns a row only if the document should be (re)indexed, preventing race conditions
    # when multiple workers process the same document concurrently.
    # Also sets updated_at so stale processing rows can be detected and reclaimed.
    claimed = await query(
        """
        INSERT INTO documents
            (title, content, source_blob, last_modified, file_hash, indexing_status)
        VALUES (%(blob)s, '', %(blob)s, %(lm)s, %(hash)s, 'processing')
        ON CONFLICT (source_blob) DO UPDATE
            SET indexing_status = 'processing',
                updated_at     = now()
        WHERE documents.indexing_status != 'processing'
          AND CASE documents.indexing_status
              WHEN 'ready' THEN
                  documents.last_modified IS DISTINCT FROM %(lm)s
                  OR documents.file_hash IS DISTINCT FROM %(hash)s
              WHEN 'failed' THEN %(retry)s::boolean
              ELSE true
          END
        RETURNING id;
        """,
        {"blob": blob_name, "lm": last_modified, "hash": file_hash,
         "retry": retry_failed},
    )

    if not claimed:
        logger.info("process_document: skipping '%s' (up to date or already processing)", blob_name)
        return {"status": "skipped", "blob": blob_name}

    try:
        # Step 3: extract structured blocks (font metadata preserved for heading detection)
        blocks = await extract_blocks(blob_name)

        # Step 4: structure-aware chunking
        from chunker import chunk_document, blocks_to_text
        title   = blob_name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        content = blocks_to_text(blocks)  # full text for full-text / fuzzy search
        t0 = time.perf_counter()
        raw_chunks = chunk_document(blocks, document_name=title, source_blob=blob_name)
        logger.info(
            "chunk_document: '%s' → %d chunks (%.3fs)",
            blob_name, len(raw_chunks), time.perf_counter() - t0,
        )

        # Guard: if structured extraction yielded no usable content, fall back
        # to plain text extraction so we don't silently index an empty document.
        if not content.strip() and not raw_chunks:
            logger.warning(
                "process_document: structured extraction empty for '%s' — falling back to extract_text()",
                blob_name,
            )
            content = await extract_text(blob_name)
            if not content.strip():
                await update_index_status(blob_name, "failed", error="No extractable text")
                return {"status": "error", "blob": blob_name, "error": "No extractable text"}
            # Re-chunk is not attempted; content will serve full-text/fuzzy search.
            # Chunks stay empty — semantic search falls back to document-level embedding.

        # Step 5: save document row — keep status='processing' until chunks
        # are fully written so a crash here doesn't leave a 'ready' doc with
        # missing chunks (no document-level embedding — semantic search now
        # uses per-chunk embeddings stored in the chunks table)
        doc_id = await save_indexed_document(
            blob_name=blob_name,
            title=title,
            content=content,
            last_modified=last_modified,
            file_hash=file_hash,
            embeddings=None,
            indexing_status="processing",
        )

        # Step 6: embed and save chunks
        t0 = time.perf_counter()
        chunk_count, embedded_count = await save_chunks(doc_id, raw_chunks)
        logger.info(
            "save_chunks: '%s' → %d chunks saved, %d with embeddings (%.3fs)",
            blob_name, chunk_count, embedded_count, time.perf_counter() - t0,
        )

        # Fallback: if no chunk embeddings were generated but we have content,
        # attempt a document-level embedding so semantic search can still find
        # this document via the documents.embedding fallback path.
        all_chunks_embedded = (embedded_count == chunk_count and chunk_count > 0)
        has_any_embedding = embedded_count > 0
        if embedded_count == 0 and content.strip():
            logger.warning(
                "process_document: no chunk embeddings for '%s' — attempting document-level fallback",
                blob_name,
            )
            doc_embedding = await generate_embeddings(chunk_text(content))
            if doc_embedding:
                await execute(
                    "UPDATE documents SET embedding = %(emb)s::vector WHERE id = %(id)s",
                    {"emb": json.dumps(doc_embedding), "id": doc_id},
                )
                logger.info("process_document: document-level embedding saved for '%s'", blob_name)
                has_any_embedding = True
            else:
                logger.warning(
                    "process_document: document-level embedding also failed for '%s' "
                    "— semantic search unavailable until re-index with working embeddings",
                    blob_name,
                )

        # Step 7: flip status.
        # 'ready'   = fully indexed: content + ALL chunk embeddings available
        # 'partial' = content indexed for full-text/fuzzy, but some or all
        #             embeddings missing → automatically retried on next run
        if all_chunks_embedded:
            await update_index_status(blob_name, "ready")
            return {"status": "ok", "blob": blob_name, "document_id": doc_id, "chunks": chunk_count}
        elif has_any_embedding:
            await update_index_status(blob_name, "partial")
            logger.warning(
                "process_document: '%s' set to 'partial' — %d/%d chunk embeddings succeeded; "
                "retrying missing embeddings on next pipeline run",
                blob_name, embedded_count, chunk_count,
            )
            return {"status": "partial", "blob": blob_name, "document_id": doc_id, "chunks": chunk_count}
        else:
            await update_index_status(blob_name, "partial")
            logger.warning(
                "process_document: '%s' set to 'partial' — full-text/fuzzy OK, "
                "semantic search unavailable until embeddings succeed",
                blob_name,
            )
            return {"status": "partial", "blob": blob_name, "document_id": doc_id, "chunks": chunk_count}

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

    # Reclaim stale processing rows — documents stuck in 'processing' from a
    # previous crashed or killed worker.  Reset them to 'new' so they are
    # re-evaluated and re-indexed on this run.
    stale = await query(
        """
        UPDATE documents
        SET indexing_status = 'new',
            error_message   = 'Reclaimed from stale processing state'
        WHERE indexing_status = 'processing'
          AND updated_at < now() - make_interval(mins => %(mins)s)
        RETURNING source_blob;
        """,
        {"mins": _STALE_PROCESSING_MINUTES},
    )
    if stale:
        logger.warning(
            "run_pipeline: reclaimed %d stale processing document(s): %s",
            len(stale), [r["source_blob"] for r in stale],
        )

    # Step 1: discover
    blobs = await discover_documents()
    if not blobs:
        return {"status": "ok", "total": 0, "message": "No documents found in Blob Storage."}

    if force:
        # Reset all to 'new' so every document gets reprocessed.
        # Single batch UPDATE avoids N sequential round-trips.
        blob_names = [blob["name"] for blob in blobs]
        await execute(
            "UPDATE documents SET indexing_status = 'new' WHERE source_blob = ANY(%(blobs)s)",
            {"blobs": blob_names},
        )
        logger.info("run_pipeline: force-reset %d documents", len(blob_names))

    # Process with bounded concurrency (avoids hammering DB and Blob Storage)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def process_with_limit(blob):
        async with semaphore:
            return await process_document(blob, retry_failed=retry_failed)

    results = await asyncio.gather(*[process_with_limit(blob) for blob in blobs])

    ok      = [r for r in results if r["status"] == "ok"]
    partial = [r for r in results if r["status"] == "partial"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed  = [r for r in results if r["status"] == "error"]

    elapsed = time.perf_counter() - t_total
    logger.info(
        "run_pipeline: done in %.2fs — %d indexed, %d partial, %d skipped, %d failed",
        elapsed, len(ok), len(partial), len(skipped), len(failed),
    )

    return {
        "status": "ok",
        "total": len(blobs),
        "indexed": len(ok),
        "partial": len(partial),
        "skipped": len(skipped),
        "failed": len(failed),
        "elapsed_seconds": round(elapsed, 2),
        "partial_files": [r["blob"] for r in partial],
        "failed_files": [{"blob": r["blob"], "error": r.get("error")} for r in failed],
    }
