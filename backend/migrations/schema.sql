-- schema.sql — canonical documents table definition
--
-- This is the single source of truth for a fresh database setup.
-- It replaces migrations 001–006, which were applied incrementally during development.
-- Run this file on a NEW database. On an existing database, use the numbered migrations.
--
-- Prerequisites (run once on the database):
--   CREATE EXTENSION IF NOT EXISTS vector;
--   CREATE EXTENSION IF NOT EXISTS pg_trgm;
--
-- Usage:
--   psql $DATABASE_URL -f backend/migrations/schema.sql

CREATE TABLE IF NOT EXISTS documents (
    id               SERIAL PRIMARY KEY,
    title            TEXT        NOT NULL,
    content          TEXT        NOT NULL DEFAULT '',

    -- Azure Blob Storage reference; one row per file, NULLs allowed for manual entries
    source_blob      TEXT,
    CONSTRAINT uq_documents_source_blob UNIQUE (source_blob),

    -- Full-text search vector (Norwegian), kept in sync by trigger below
    search_vector    TSVECTOR,

    -- Semantic search embedding (pgvector). 1536 dims = OpenAI text-embedding-3-small.
    -- Change dimension if using a different model.
    embedding        vector(1536),

    -- Ingest pipeline tracking
    last_modified    TIMESTAMPTZ,                              -- blob last-modified from Azure
    file_hash        TEXT,                                     -- blob etag; changes when content changes
    indexing_status  TEXT        NOT NULL DEFAULT 'new',       -- new | processing | ready | partial | failed
    indexed_at       TIMESTAMPTZ,
    error_message    TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Full-text search: GIN index on tsvector
CREATE INDEX IF NOT EXISTS idx_documents_search_vector
    ON documents USING GIN (search_vector);

-- Fuzzy search: trigram GIN indexes on title and content (pg_trgm)
CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
    ON documents USING GIN (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_documents_content_trgm
    ON documents USING GIN (content gin_trgm_ops);

-- Semantic search: HNSW index for cosine similarity (pgvector)
CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
    ON documents USING hnsw (embedding vector_cosine_ops);

-- Status filtering (e.g. find all documents needing processing)
CREATE INDEX IF NOT EXISTS idx_documents_indexing_status
    ON documents (indexing_status);

-- Trigger: keep search_vector and updated_at in sync on every INSERT/UPDATE
CREATE OR REPLACE FUNCTION documents_search_vector_update() RETURNS trigger AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('norwegian', COALESCE(NEW.title, '')), 'A') ||
        setweight(to_tsvector('norwegian', COALESCE(NEW.content, '')), 'B');
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_documents_search_vector ON documents;
CREATE TRIGGER trg_documents_search_vector
    BEFORE INSERT OR UPDATE OF title, content
    ON documents
    FOR EACH ROW
    EXECUTE FUNCTION documents_search_vector_update();

-- ============================================================================
-- Chunks table — structure-aware semantic search
-- ============================================================================
-- Each document may have zero or more chunks produced by chunker.py.
-- Semantic search queries chunk embeddings for higher retrieval precision.
--
-- CANONICAL DEFINITION: migrations/007_create_chunks_table.sql
-- Keep this copy in sync with the migration file above.

CREATE TABLE IF NOT EXISTS chunks (
    id               SERIAL PRIMARY KEY,
    document_id      INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    parent_chunk_id  INTEGER REFERENCES chunks(id) ON DELETE CASCADE,
    chunk_index      INTEGER NOT NULL,
    text             TEXT    NOT NULL,
    char_count       INTEGER NOT NULL,
    file_type        TEXT,
    heading_path     TEXT,
    section_title    TEXT,
    section_number   TEXT,
    page_start       INTEGER,
    page_end         INTEGER,
    topic_type       TEXT,
    alternative      TEXT,
    delomrade        TEXT,
    contains_table   BOOLEAN NOT NULL DEFAULT FALSE,
    embedding        vector(1536),
    search_vector    TSVECTOR,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_chunks_parent_chunk_id
    ON chunks (parent_chunk_id);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops);

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
