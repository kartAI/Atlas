-- Migration 008: Create app.chat_layers table for persistent map layers
--
-- Stores drawn/AI-generated map layers per chat session so they survive
-- page reloads and can be restored when a user resumes a conversation.

CREATE TABLE IF NOT EXISTS app.chat_layers (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id     UUID        NOT NULL REFERENCES app.chats(id) ON DELETE CASCADE,
    layer_id    TEXT        NOT NULL,
    name        TEXT        NOT NULL,
    shape       TEXT        NOT NULL,
    visible     BOOLEAN     NOT NULL DEFAULT TRUE,
    geojson     JSONB       NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_chat_layers_chat_layer UNIQUE (chat_id, layer_id)
);

CREATE INDEX IF NOT EXISTS idx_chat_layers_chat_id ON app.chat_layers (chat_id);
