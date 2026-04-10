-- Phase 0 foundation schema.
-- PostgreSQL remains the source of truth; Redis only carries ephemeral state.

CREATE TABLE IF NOT EXISTS outbox_events (
    id UUID PRIMARY KEY,
    topic TEXT NOT NULL,
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_outbox_events_status_created_at
    ON outbox_events (status, created_at);

CREATE TABLE IF NOT EXISTS stream_consumers (
    id UUID PRIMARY KEY,
    consumer_name TEXT NOT NULL,
    stream_name TEXT NOT NULL,
    group_name TEXT NOT NULL,
    last_heartbeat_at TIMESTAMPTZ NULL,
    last_delivered_id TEXT NULL,
    pending_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (consumer_name, stream_name, group_name)
);

CREATE INDEX IF NOT EXISTS idx_stream_consumers_stream_group
    ON stream_consumers (stream_name, group_name);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id UUID PRIMARY KEY,
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    response_payload JSONB NULL,
    expires_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (scope, key)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_keys_status_expires_at
    ON idempotency_keys (status, expires_at);
