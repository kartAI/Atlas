-- Migration: rebuild the chunks-by-document index to preserve reading order.
--
-- Existing databases may already have idx_chunks_document_id from migration 007
-- on (document_id) only. Recreate it with chunk_index included so sequential
-- chunk reads can use the index order directly.

DROP INDEX IF EXISTS idx_chunks_document_id;

CREATE INDEX IF NOT EXISTS idx_chunks_document_id
    ON chunks (document_id, chunk_index);
