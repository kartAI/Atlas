-- schema.sql — canonical documents table definition
--
-- This is the single source of truth for a fresh database setup.
-- It replaces migrations 001–005, which were applied incrementally during development.
-- Run this file on a NEW database. On an existing database, use the numbered migrations.
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

    -- Placeholder for future semantic search (pgvector not yet enabled)
    embedding        JSONB,

    -- Ingest pipeline tracking
    last_modified    TIMESTAMPTZ,                              -- blob last-modified from Azure
    file_hash        TEXT,                                     -- blob etag; changes when content changes
    indexing_status  TEXT        NOT NULL DEFAULT 'new',       -- new | processing | ready | failed
    indexed_at       TIMESTAMPTZ,
    error_message    TEXT,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Fast full-text search lookups
CREATE INDEX IF NOT EXISTS idx_documents_search_vector
    ON documents USING GIN (search_vector);

-- Fast status filtering (e.g. find all documents needing processing)
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
