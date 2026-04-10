-- Phase 6 evolution persistence schema.

CREATE TABLE IF NOT EXISTS evolution_journal (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    event_type TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_evolution_journal_user_created_at
    ON evolution_journal (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_evolution_journal_event_type_created_at
    ON evolution_journal (event_type, created_at DESC);
