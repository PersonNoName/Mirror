-- Phase 3 memory persistence schema.
-- PostgreSQL remains the source of truth for durable core memory snapshots.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS core_memory_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, version)
);

CREATE INDEX IF NOT EXISTS idx_core_memory_snapshots_user_created_at
    ON core_memory_snapshots (user_id, created_at DESC);
