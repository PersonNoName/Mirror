-- Phase 7 mid-term memory persistence schema.

CREATE TABLE IF NOT EXISTS mid_term_memory (
    memory_key TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    topic_key TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT mid_term_memory_status_check
        CHECK (status IN ('active', 'promoted', 'expired', 'suppressed'))
);

CREATE INDEX IF NOT EXISTS mid_term_memory_user_id_idx
    ON mid_term_memory (user_id);

CREATE INDEX IF NOT EXISTS mid_term_memory_user_status_idx
    ON mid_term_memory (user_id, status);

CREATE INDEX IF NOT EXISTS mid_term_memory_user_topic_idx
    ON mid_term_memory (user_id, topic_key);
