"""
SearchService — unified search across documents.

Provides four search strategies:
  - search_full_text:  tsvector-based Norwegian full-text search  (active)
  - search_semantic:   pgvector cosine similarity                 (active — requires embeddings in DB)
  - search_fuzzy:      pg_trgm trigram similarity                 (active)
  - hybrid_search:     combines all three, tolerates missing backends

For document ingestion, see ingest_pipeline.py.
"""

import json
import logging
from db import query

logger = logging.getLogger(__name__)

_SNIPPET_LENGTH = 300
_SEMANTIC_CHUNK_CANDIDATE_MULTIPLIER = 8
_SEMANTIC_CHUNK_MIN_CANDIDATES = 100


def _with_snippets(rows) -> list[dict]:
    """Convert rows to dicts and truncate content to a short snippet."""
    results = []
    for r in rows:
        d = dict(r)
        content = d.get("content", "")
        if len(content) > _SNIPPET_LENGTH:
            d["content"] = content[:_SNIPPET_LENGTH] + "…"
        results.append(d)
    return results

async def search_full_text(search_query: str, limit: int = 10) -> list[dict]:
    """
    Norwegian full-text search using tsvector + plainto_tsquery.
    Returns documents ranked by relevance (ts_rank).
    """
    if not search_query or not search_query.strip():
        return []

    rows = await query(
        """
        SELECT
            id,
            title,
            content,
            ts_rank(search_vector, plainto_tsquery('norwegian', %(q)s)) AS score
        FROM documents
        WHERE search_vector @@ plainto_tsquery('norwegian', %(q)s)
          AND indexing_status IN ('ready', 'partial')
        ORDER BY score DESC
        LIMIT %(lim)s;
        """,
        {"q": search_query.strip(), "lim": limit},
    )
    logger.info("search_full_text: query='%s' → %d treff", search_query.strip(), len(rows))
    return _with_snippets(rows)


async def search_semantic(search_query: str, limit: int = 10) -> list[dict]:
    """
    Semantic search using pgvector cosine distance.

    Queries the chunks table first (per-chunk embeddings = higher precision).
    Supplements with the documents table for any documents not already
    represented in the chunk results (handles the migration window where
    some documents have chunk embeddings and others only have a document-level
    embedding).

    Returns one result per unique document (best-matching chunk per document).
    Each result includes heading_path, section_title, topic_type, and page_start
    so the caller knows exactly which part of the document matched.
    """
    if not search_query or not search_query.strip():
        return []

    query_embedding = await _embed_text(search_query.strip())
    if query_embedding is None:
        logger.info("search_semantic: ingen embedding-modell konfigurert — hopper over")
        return []

    # Chunk-level semantic search (higher precision)
    chunk_results = await _search_semantic_chunks(query_embedding, search_query.strip(), limit)

    # Document-level fallback — always run so un-chunked documents are covered
    doc_results = await _search_semantic_documents(query_embedding, search_query.strip(), limit)

    if not chunk_results:
        return doc_results
    if not doc_results:
        return chunk_results

    # Merge: supplement chunk results with document-level hits for docs not
    # already represented, so partially-migrated corpora don't lose coverage.
    covered_ids = {r["id"] for r in chunk_results}
    merged = list(chunk_results)
    for doc in doc_results:
        if doc["id"] not in covered_ids:
            merged.append(doc)

    merged.sort(key=lambda d: d.get("score", 0), reverse=True)
    return merged[:limit]


async def _search_semantic_chunks(
    query_embedding: list[float],
    search_query:    str,
    limit:           int,
) -> list[dict]:
    """
    Find the best-matching chunk per document using pgvector cosine similarity.

    Fetches a limited nearest-neighbour candidate set first so PostgreSQL can
    use the pgvector HNSW index on chunks.embedding, then de-duplicates that
    candidate set down to the best chunk per document.

    Returns chunk-level content with the same snippet-length content contract
    used by the other search backends.
    """
    candidate_limit = max(
        limit * _SEMANTIC_CHUNK_CANDIDATE_MULTIPLIER,
        _SEMANTIC_CHUNK_MIN_CANDIDATES,
    )
    rows = await query(
        """
        WITH nearest_chunks AS (
            SELECT
                d.id                                              AS document_id,
                d.title                                           AS document_title,
                c.text                                            AS content,
                c.heading_path,
                c.section_title,
                c.topic_type,
                c.alternative,
                c.delomrade,
                c.contains_table,
                c.page_start,
                c.page_end,
                c.chunk_index,
                c.id                                              AS chunk_id,
                1 - (c.embedding <=> %(emb)s::vector)             AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.embedding IS NOT NULL
              AND d.indexing_status IN ('ready', 'partial')
            ORDER BY c.embedding <=> %(emb)s::vector
            LIMIT %(candidate_lim)s
        )
        SELECT *
        FROM (
            SELECT DISTINCT ON (nc.document_id)
                nc.document_id                                    AS id,
                nc.document_title                                 AS title,
                nc.content,
                nc.heading_path,
                nc.section_title,
                nc.topic_type,
                nc.alternative,
                nc.delomrade,
                nc.contains_table,
                nc.page_start,
                nc.page_end,
                nc.chunk_index,
                nc.chunk_id,
                nc.score
            FROM nearest_chunks nc
            ORDER BY nc.document_id, nc.score DESC
        ) best_per_doc
        ORDER BY score DESC
        LIMIT %(lim)s;
        """,
        {"emb": json.dumps(query_embedding), "lim": limit, "candidate_lim": candidate_limit},
    )
    logger.info(
        "search_semantic (chunks): query='%s' → %d treff from %d candidates",
        search_query, len(rows), candidate_limit,
    )
    return _with_snippets(rows)


async def _search_semantic_documents(
    query_embedding: list[float],
    search_query:    str,
    limit:           int,
) -> list[dict]:
    """
    Fallback: document-level cosine similarity search on documents.embedding.
    Used when the chunks table has no embeddings yet.
    """
    rows = await query(
        """
        SELECT
            id,
            title,
            content,
            1 - (embedding <=> %(emb)s::vector) AS score
        FROM documents
        WHERE embedding IS NOT NULL
          AND indexing_status IN ('ready', 'partial')
        ORDER BY embedding <=> %(emb)s::vector
        LIMIT %(lim)s;
        """,
        {"emb": json.dumps(query_embedding), "lim": limit},
    )
    logger.info("search_semantic (documents fallback): query='%s' → %d treff", search_query, len(rows))
    return _with_snippets([dict(r) for r in rows])


async def search_fuzzy(search_query: str, limit: int = 10) -> list[dict]:
    """
    Fuzzy search using pg_trgm trigram similarity.

    Uses similarity() on title and word_similarity() on content.
    word_similarity finds the best matching substring within long text,
    which works better than similarity() when the query is short.
    """
    if not search_query or not search_query.strip():
        return []

    rows = await query(
        """
        SELECT
            id,
            title,
            content,
            GREATEST(
                similarity(title, %(q)s),
                word_similarity(%(q)s, content)
            ) AS score
        FROM documents
        WHERE (similarity(title, %(q)s) > 0.1
           OR word_similarity(%(q)s, content) > 0.1)
          AND indexing_status IN ('ready', 'partial')
        ORDER BY score DESC
        LIMIT %(lim)s;
        """,
        {"q": search_query.strip(), "lim": limit},
    )
    logger.info("search_fuzzy: query='%s' → %d treff", search_query.strip(), len(rows))
    return _with_snippets(rows)


async def hybrid_search(search_query: str, limit: int = 10) -> list[dict]:
    """
    Combines results from full-text, semantic, and fuzzy search.
    Deduplicates by document id and keeps the highest score per document.
    Tags each result with which search method found it.
    Tolerates failures in individual backends.
    """
    combined: dict[int, dict] = {}

    # Full-text search (primary)
    try:
        for doc in await search_full_text(search_query, limit):
            doc_id = doc["id"]
            doc["source"] = "fulltext"
            combined[doc_id] = doc
    except Exception as e:
        logger.warning("hybrid_search: fulltekstsøk feilet: %s", e)

    # Semantic search (pgvector — returns empty if no embeddings exist yet)
    try:
        for doc in await search_semantic(search_query, limit):
            doc_id = doc["id"]
            if doc_id not in combined or doc["score"] > combined[doc_id]["score"]:
                doc["source"] = "semantic"
                combined[doc_id] = doc
    except Exception as e:
        logger.warning("hybrid_search: semantisk søk feilet: %s", e)

    # Fuzzy search (pg_trgm)
    try:
        for doc in await search_fuzzy(search_query, limit):
            doc_id = doc["id"]
            if doc_id not in combined or doc["score"] > combined[doc_id]["score"]:
                doc["source"] = "fuzzy"
                combined[doc_id] = doc
    except Exception as e:
        logger.warning("hybrid_search: fuzzy-søk feilet: %s", e)

    results = sorted(combined.values(), key=lambda d: d.get("score", 0), reverse=True)
    logger.info(
        "hybrid_search: query='%s' → %d unike treff (fulltext=%d, semantic=%d, fuzzy=%d)",
        search_query.strip(),
        len(results),
        sum(1 for d in results if d.get("source") == "fulltext"),
        sum(1 for d in results if d.get("source") == "semantic"),
        sum(1 for d in results if d.get("source") == "fuzzy"),
    )
    return results[:limit]


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

async def _embed_text(text: str) -> list[float] | None:
    """
    Convert text to an embedding vector using GitHub Models API.
    Returns None if the token is not configured (safe fallback).
    """
    try:
        from embedding_client import get_single_embedding
        return await get_single_embedding(text)
    except ValueError as e:
        logger.warning("_embed_text: %s", e)
        return None
    except Exception as e:
        logger.error("_embed_text: API call failed: %s", e)
        return None
