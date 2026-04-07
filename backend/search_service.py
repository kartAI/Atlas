"""
SearchService — unified search across documents.

Provides four search strategies:
  - search_full_text:  tsvector-based Norwegian full-text search  (active)
  - search_semantic:   pgvector cosine similarity                 (active — requires embeddings in DB)
  - search_fuzzy:      pg_trgm trigram similarity                 (active)
  - hybrid_search:     combines all three, tolerates missing backends

For document ingestion, see ingest_pipeline.py.
"""

import logging
from db import query

logger = logging.getLogger(__name__)

# Embedding dimension must match the model used in ingest_pipeline.py.
# 1536 = OpenAI text-embedding-3-small / ada-002.
EMBEDDING_DIMENSIONS = 1536


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
        ORDER BY score DESC
        LIMIT %(lim)s;
        """,
        {"q": search_query.strip(), "lim": limit},
    )
    logger.info("search_full_text: query='%s' → %d treff", search_query.strip(), len(rows))
    return [dict(r) for r in rows]


async def search_semantic(search_query: str, limit: int = 10) -> list[dict]:
    """
    Semantic search using pgvector cosine distance.

    Embeds the query text and finds the nearest documents by cosine similarity.
    Returns empty if no embedding model is configured or no documents have embeddings.
    """
    if not search_query or not search_query.strip():
        return []

    # Generate embedding for the query text
    query_embedding = await _embed_text(search_query.strip())
    if query_embedding is None:
        logger.info("search_semantic: ingen embedding-modell konfigurert — hopper over")
        return []

    # Cosine similarity = 1 - cosine distance (<=> operator)
    rows = await query(
        """
        SELECT
            id,
            title,
            content,
            1 - (embedding <=> %(emb)s::vector) AS score
        FROM documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %(emb)s::vector
        LIMIT %(lim)s;
        """,
        {"emb": str(query_embedding), "lim": limit},
    )
    logger.info("search_semantic: query='%s' → %d treff", search_query.strip(), len(rows))
    return [dict(r) for r in rows]


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
        WHERE similarity(title, %(q)s) > 0.1
           OR word_similarity(%(q)s, content) > 0.1
        ORDER BY score DESC
        LIMIT %(lim)s;
        """,
        {"q": search_query.strip(), "lim": limit},
    )
    logger.info("search_fuzzy: query='%s' → %d treff", search_query.strip(), len(rows))
    return [dict(r) for r in rows]


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
            if doc_id not in combined:
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
# Embedding helper (stub — replace when model is chosen)
# ---------------------------------------------------------------------------

async def _embed_text(text: str) -> list[float] | None:
    """
    Convert text to an embedding vector.

    STUB — returns None until an embedding model/API is configured.

    To activate semantic search, replace this with one of:
      1. OpenAI:  openai.embeddings.create(model="text-embedding-3-small", input=text)
      2. Local:   sentence_transformers.SentenceTransformer("all-MiniLM-L6-v2").encode(text)

    The returned list must have exactly EMBEDDING_DIMENSIONS floats (currently 1536).
    If using a different model, update EMBEDDING_DIMENSIONS and re-run migration 006.
    """
    # TODO: Implement when embedding model is chosen.
    #
    # Example with OpenAI:
    #   import openai
    #   response = await openai.AsyncOpenAI().embeddings.create(
    #       model="text-embedding-3-small", input=text
    #   )
    #   return response.data[0].embedding
    #
    return None
