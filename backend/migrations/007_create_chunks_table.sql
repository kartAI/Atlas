-- Migration: Create chunks table for structure-aware semantic search.
--
-- Each document row in the documents table may have zero or more associated chunks.
-- Chunks are produced by the structure-aware chunking pipeline (chunker.py).
-- Semantic search queries chunk embeddings instead of document-level averaged embeddings.
--
-- Two-level hierarchy:
--   parent_chunk_id IS NULL  → top-level section chunk
--   parent_chunk_id IS NOT NULL → child chunk inside a large section

CREATE TABLE IF NOT EXISTS chunks (
    id               SERIAL PRIMARY KEY,

    -- Parent document (one-to-many, cascade delete when document is removed)
    document_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,

    -- Self-referencing parent for two-level chunking (NULL = top-level)
    parent_chunk_id  INTEGER REFERENCES chunks(id) ON DELETE CASCADE,

    -- Order within the document (for reconstructing reading order)
    chunk_index      INTEGER NOT NULL,

    -- Content
    text             TEXT    NOT NULL,
    char_count       INTEGER NOT NULL,
    file_type        TEXT,                        -- e.g. "pdf"

    -- Structure metadata
    heading_path     TEXT,                        -- e.g. "5 Vurdering av påvirkning > 5.1 Alternativ 1"
    section_title    TEXT,
    section_number   TEXT,                        -- e.g. "5.1"
    page_start       INTEGER,
    page_end         INTEGER,

    -- Classification metadata
    topic_type       TEXT,                        -- summary | introduction | project_description |
                                                  -- method | value_assessment | impact_assessment |
                                                  -- consequence | mitigation | law | uncertainty |
                                                  -- references | table | other
    alternative      TEXT,                        -- e.g. "nullalternativ" | "alternativ 1"
    delomrade        TEXT,                        -- e.g. "N01" | "ØFA1"
    contains_table   BOOLEAN NOT NULL DEFAULT FALSE,

    -- Semantic search embedding (pgvector). NULL until embedding is generated.
    embedding        vector(1536),

    -- Full-text search vector (Norwegian), for potential chunk-level full-text search.
    search_vector    TSVECTOR,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fast lookup of all chunks for a given document and reading-order reconstruction.
CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id, chunk_index);

-- Fast lookup of child chunks for a given parent chunk
CREATE INDEX IF NOT EXISTS idx_chunks_parent_chunk_id
    ON chunks (parent_chunk_id);

-- HNSW index for fast cosine-similarity search (pgvector).
-- Only indexes non-NULL embeddings; NULL rows are excluded automatically.
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

-- GIN index for future chunk-level full-text search (pg_trgm / tsvector)
CREATE INDEX IF NOT EXISTS idx_chunks_search_vector
    ON chunks USING GIN (search_vector);

-- Trigger: auto-populate search_vector on INSERT/UPDATE (mirrors documents trigger)
CREATE OR REPLACE FUNCTION chunks_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector := to_tsvector('norwegian', COALESCE(NEW.text, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_chunks_search_vector ON chunks;
CREATE TRIGGER trg_chunks_search_vector
    BEFORE INSERT OR UPDATE OF text
    ON chunks
    FOR EACH ROW
    EXECUTE FUNCTION chunks_search_vector_update();
