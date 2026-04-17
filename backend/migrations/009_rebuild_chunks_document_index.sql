-- Migration 009: rebuild chunks-by-document index for ordered reads.
--
-- Migration 007 now creates idx_chunks_document_id on (document_id, chunk_index),
-- but databases that already applied the original 007 still have the old
-- single-column index on (document_id). Rebuild that existing index so re-index
-- and sequential chunk reads preserve document order everywhere.

-- Drop the legacy index definition first, then recreate it with chunk_index.
-- Both statements are idempotent, so this migration is safe to re-run.
DROP INDEX IF EXISTS idx_chunks_document_id;

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id, chunk_index);
