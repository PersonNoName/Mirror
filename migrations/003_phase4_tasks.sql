-- Phase 4 task system schema.

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    parent_task_id UUID NULL,
    assigned_to TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 1,
    result JSONB NULL,
    error_trace TEXT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    dispatch_stream TEXT NOT NULL DEFAULT 'stream:task:dispatch',
    consumer_group TEXT NOT NULL DEFAULT 'main-agent',
    delivery_token TEXT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status_created_at
    ON tasks (status, created_at);
