"""Persistent PostgreSQL-backed outbox store with memory fallback."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover - optional dependency in local planning env
    asyncpg = None

from app.config import settings
from app.infra.outbox import OutboxEvent


class OutboxStore:
    """Persist outbox events in PostgreSQL and mirror them in memory when degraded."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres.dsn
        self._pool: Any | None = None
        self._memory: dict[str, OutboxEvent] = {}
        self.degraded = asyncpg is None

    async def initialize(self) -> None:
        if asyncpg is None:
            self.degraded = True
            return
        try:
            self._pool = await asyncpg.create_pool(dsn=self.dsn)
        except Exception:
            self.degraded = True

    async def enqueue(self, event: OutboxEvent) -> OutboxEvent:
        self._memory[event.id] = event
        if self.degraded or self._pool is None:
            return event
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO outbox_events (
                    id, topic, payload, status, retry_count,
                    next_retry_at, created_at, published_at
                ) VALUES (
                    $1, $2, $3::jsonb, $4, $5, $6, $7, $8
                )
                ON CONFLICT (id) DO UPDATE SET
                    topic = EXCLUDED.topic,
                    payload = EXCLUDED.payload,
                    status = EXCLUDED.status,
                    retry_count = EXCLUDED.retry_count,
                    next_retry_at = EXCLUDED.next_retry_at,
                    created_at = EXCLUDED.created_at,
                    published_at = EXCLUDED.published_at
                """,
                event.id,
                event.topic,
                json.dumps(event.payload, default=self._json_default, ensure_ascii=False),
                event.status,
                event.retry_count,
                event.next_retry_at,
                event.created_at,
                event.published_at,
            )
        return event

    async def list_pending(self, limit: int = 100) -> list[OutboxEvent]:
        if self.degraded or self._pool is None:
            now = datetime.now(timezone.utc)
            return [
                event
                for event in self._memory.values()
                if event.status == "pending" and (event.next_retry_at is None or event.next_retry_at <= now)
            ][:limit]
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, topic, payload, status, retry_count, next_retry_at, created_at, published_at
                FROM outbox_events
                WHERE status = 'pending'
                  AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                ORDER BY created_at ASC
                LIMIT $1
                """,
                limit,
            )
        events = [self._row_to_event(row) for row in rows]
        for event in events:
            self._memory[event.id] = event
        return events

    async def mark_published(self, event_id: str) -> None:
        event = self._memory.get(event_id)
        if event is not None:
            event.status = "published"
            event.published_at = datetime.now(timezone.utc)
            self._memory[event_id] = event
        if self.degraded or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox_events
                SET status = 'published', published_at = NOW()
                WHERE id = $1
                """,
                event_id,
            )

    async def schedule_retry(self, event_id: str, retry_count: int, error: str | None = None) -> None:
        next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=min(60, 2**max(retry_count, 1)))
        event = self._memory.get(event_id)
        if event is not None:
            event.retry_count = retry_count
            event.next_retry_at = next_retry_at
            event.status = "pending"
            if error:
                event.payload.setdefault("metadata", {})["relay_error"] = error
            self._memory[event_id] = event
        if self.degraded or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE outbox_events
                SET retry_count = $2,
                    next_retry_at = $3,
                    status = 'pending'
                WHERE id = $1
                """,
                event_id,
                retry_count,
                next_retry_at,
            )

    async def ack_consumed(self, scope: str, event_id: str) -> None:
        if self.degraded:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO idempotency_keys (id, scope, key, status)
                VALUES (gen_random_uuid(), $1, $2, 'completed')
                ON CONFLICT (scope, key) DO NOTHING
                """,
                scope,
                event_id,
            )

    @staticmethod
    def from_payload(topic: str, payload: dict[str, Any]) -> OutboxEvent:
        return OutboxEvent(topic=topic, payload=payload)

    @staticmethod
    def _json_default(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "__dict__"):
            return value.__dict__
        return str(value)

    @staticmethod
    def _row_to_event(row: Any) -> OutboxEvent:
        payload = row["payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return OutboxEvent(
            id=str(row["id"]),
            topic=row["topic"],
            payload=dict(payload),
            status=row["status"],
            retry_count=row["retry_count"],
            next_retry_at=row["next_retry_at"],
            created_at=row["created_at"],
            published_at=row["published_at"],
        )
