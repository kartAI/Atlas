-- Migration 009: Add metadata column to app.messages
--
-- Stores per-message metadata as JSONB. Used by the thinking-traces feature
-- to persist reasoning traces on assistant messages and tool_hints on user
-- messages.

ALTER TABLE app.messages
    ADD COLUMN IF NOT EXISTS metadata JSONB;
