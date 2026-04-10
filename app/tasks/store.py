"""Task persistence with PostgreSQL-first, memory-fallback behavior."""

from __future__ import annotations

from dataclasses import replace
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
        self._memory[task.id] = replace(task)
        if self.degraded or self._pool is None:
            return task

        payload = self._serialize_task(task)
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
                ON CONFLICT (id) DO UPDATE SET
                    parent_task_id = EXCLUDED.parent_task_id,
                    assigned_to = EXCLUDED.assigned_to,
                    intent = EXCLUDED.intent,
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    result = EXCLUDED.result,
                    error_trace = EXCLUDED.error_trace,
                    retry_count = EXCLUDED.retry_count,
                    timeout_seconds = EXCLUDED.timeout_seconds,
                    last_heartbeat_at = EXCLUDED.last_heartbeat_at,
                    dispatch_stream = EXCLUDED.dispatch_stream,
                    consumer_group = EXCLUDED.consumer_group,
                    delivery_token = EXCLUDED.delivery_token,
                    metadata = EXCLUDED.metadata,
                    created_at = EXCLUDED.created_at
                """,
                *payload,
            )
        return task

    async def get(self, task_id: str) -> Task | None:
        task = self._memory.get(task_id)
        if task is not None:
            return replace(task)
        if self.degraded or self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
        if row is None:
            return None
        task = self._deserialize_task(row)
        self._memory[task.id] = replace(task)
        return replace(task)

    async def update(self, task: Task) -> Task:
        self._memory[task.id] = replace(task)
        if self.degraded or self._pool is None:
            return task
        payload = self._serialize_task(task)
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE tasks
                SET
                    parent_task_id = $2,
                    assigned_to = $3,
                    intent = $4,
                    status = $5,
                    priority = $6,
                    result = $7::jsonb,
                    error_trace = $8,
                    retry_count = $9,
                    timeout_seconds = $10,
                    last_heartbeat_at = $11,
                    dispatch_stream = $12,
                    consumer_group = $13,
                    delivery_token = $14,
                    metadata = $15::jsonb,
                    created_at = $16
                WHERE id = $1
                """,
                *payload,
            )
        return task

    async def get_by_status(self, status: str) -> list[Task]:
        if not self.degraded and self._pool is not None:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("SELECT * FROM tasks WHERE status = $1 ORDER BY created_at ASC", status)
            tasks = [self._deserialize_task(row) for row in rows]
            for task in tasks:
                self._memory[task.id] = replace(task)
            return [replace(task) for task in tasks]
        return [replace(task) for task in self._memory.values() if task.status == status]

    async def update_heartbeat(self, task_id: str, heartbeat_at: Any) -> None:
        task = self._memory.get(task_id)
        if task is None:
            task = await self.get(task_id)
            if task is None:
                return
        task.last_heartbeat_at = heartbeat_at
        self._memory[task_id] = replace(task)
        if self.degraded or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE tasks SET last_heartbeat_at = $2 WHERE id = $1",
                task_id,
                heartbeat_at,
            )

    async def next_retry_at(self, retry_count: int) -> Any:
        return utc_now()

    @staticmethod
    def _serialize_task(task: Task) -> tuple[Any, ...]:
        metadata = dict(task.metadata)
        metadata["_task_fields"] = {
            "children_task_ids": task.children_task_ids,
            "prompt_snapshot": task.prompt_snapshot,
            "max_retries": task.max_retries,
            "heartbeat_timeout": task.heartbeat_timeout,
            "depends_on": task.depends_on,
        }
        return (
            task.id,
            task.parent_task_id,
            task.assigned_to,
            task.intent,
            task.status,
            task.priority,
            task.result,
            task.error_trace,
            task.retry_count,
            task.timeout_seconds,
            task.last_heartbeat_at,
            task.dispatch_stream,
            task.consumer_group,
            task.delivery_token,
            metadata,
            task.created_at,
        )

    @staticmethod
    def _deserialize_task(row: Any) -> Task:
        raw_metadata = dict(row["metadata"] or {})
        reserved = dict(raw_metadata.pop("_task_fields", {}))
        return Task(
            id=str(row["id"]),
            parent_task_id=str(row["parent_task_id"]) if row["parent_task_id"] else None,
            children_task_ids=list(reserved.get("children_task_ids", [])),
            assigned_to=row["assigned_to"] or "",
            intent=row["intent"] or "",
            prompt_snapshot=reserved.get("prompt_snapshot", ""),
            status=row["status"],
            priority=row["priority"],
            depends_on=list(reserved.get("depends_on", [])),
            result=row["result"],
            error_trace=row["error_trace"],
            retry_count=row["retry_count"],
            max_retries=int(reserved.get("max_retries", 2)),
            timeout_seconds=row["timeout_seconds"],
            last_heartbeat_at=row["last_heartbeat_at"],
            heartbeat_timeout=int(reserved.get("heartbeat_timeout", 30)),
            dispatch_stream=row["dispatch_stream"] or "stream:task:dispatch",
            consumer_group=row["consumer_group"] or "main-agent",
            delivery_token=row["delivery_token"],
            created_at=row["created_at"],
            metadata=raw_metadata,
        )
