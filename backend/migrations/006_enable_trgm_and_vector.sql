-- Migration: Enable pg_trgm + pgvector search capabilities.
--
-- Requires: CREATE EXTENSION vector; CREATE EXTENSION pg_trgm;
-- (already done manually on the database)

-- 1. Convert embedding column from text to vector(1536).
--    1536 dimensions = OpenAI text-embedding-3-small / ada-002 compatible.
--    Change this if using a different embedding model.
--    All existing values are NULL, so no data is lost.
ALTER TABLE documents DROP COLUMN IF EXISTS embedding;
ALTER TABLE documents ADD COLUMN embedding vector(1536);

-- 2. Trigram indexes for fuzzy search via pg_trgm.
--    GIN index with gin_trgm_ops enables the % (similarity) operator.
CREATE INDEX IF NOT EXISTS idx_documents_title_trgm
    ON documents USING GIN (title gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_documents_content_trgm
    ON documents USING GIN (content gin_trgm_ops);

-- 3. HNSW index for fast cosine-similarity search via pgvector.
--    HNSW works on empty tables (unlike IVFFlat) and is the recommended default.
CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
    ON documents USING hnsw (embedding vector_cosine_ops);
