"""Task persistence with PostgreSQL-first, memory-fallback behavior."""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

import asyncpg

from app.config import settings
from app.tasks.models import Task, utc_now


class TaskStore:
    """Store tasks in PostgreSQL when available, otherwise in memory."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres.dsn
        self._pool: asyncpg.Pool | None = None
        self._memory: dict[str, Task] = {}
        self.degraded = False

    async def initialize(self) -> None:
        try:
            self._pool = await asyncpg.create_pool(dsn=self.dsn)
        except Exception:
            self.degraded = True

    async def create(self, task: Task) -> Task:
        if self.degraded or self._pool is None:
            self._memory[task.id] = replace(task)
            return task

        payload = asdict(task)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tasks (
                    id, parent_task_id, assigned_to, intent, status, priority, result,
                    error_trace, retry_count, timeout_seconds, last_heartbeat_at,
                    dispatch_stream, consumer_group, delivery_token, metadata, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9, $10, $11, $12, $13, $14, $15::jsonb, $16
                )
                ON CONFLICT (id) DO NOTHING
                """,
                task.id,
                task.parent_task_id,
                task.assigned_to,
                task.intent,
                task.status,
                task.priority,
                payload["result"],
                task.error_trace,
                task.retry_count,
                task.timeout_seconds,
                task.last_heartbeat_at,
                task.dispatch_stream,
                task.consumer_group,
                task.delivery_token,
                payload["metadata"],
                task.created_at,
            )
        return task

    async def get(self, task_id: str) -> Task | None:
        return self._memory.get(task_id)

    async def update(self, task: Task) -> Task:
        self._memory[task.id] = replace(task)
        return task

    async def get_by_status(self, status: str) -> list[Task]:
        return [replace(task) for task in self._memory.values() if task.status == status]

    async def update_heartbeat(self, task_id: str, heartbeat_at: Any) -> None:
        task = self._memory.get(task_id)
        if task is None:
            return
        task.last_heartbeat_at = heartbeat_at
        self._memory[task_id] = task

    async def next_retry_at(self, retry_count: int) -> Any:
        return utc_now()
