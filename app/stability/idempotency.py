"""Idempotency helpers backed by PostgreSQL or memory fallback."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None

from app.config import settings


class IdempotencyStore:
    """Claim and complete event-processing keys."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres.dsn
        self._pool: Any | None = None
        self._memory: dict[tuple[str, str], str] = {}
        self.degraded = asyncpg is None

    async def initialize(self) -> None:
        if asyncpg is None:
            self.degraded = True
            return
        try:
            self._pool = await asyncpg.create_pool(dsn=self.dsn)
        except Exception:
            self.degraded = True

    async def claim(self, scope: str, key: str, ttl_hours: int = 24) -> bool:
        if self.degraded or self._pool is None:
            bucket = (scope, key)
            if self._memory.get(bucket) == "completed":
                return False
            self._memory[bucket] = "pending"
            return True
        async with self._pool.acquire() as conn:
            try:
                await conn.execute(
                    """
                    INSERT INTO idempotency_keys (id, scope, key, status, expires_at)
                    VALUES ($1, $2, $3, 'pending', $4)
                    """,
                    str(uuid4()),
                    scope,
                    key,
                    datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
                )
                return True
            except Exception:
                row = await conn.fetchrow(
                    "SELECT status FROM idempotency_keys WHERE scope = $1 AND key = $2",
                    scope,
                    key,
                )
                return row is None or row["status"] != "completed"

    async def mark_done(self, scope: str, key: str, response_payload: dict[str, Any] | None = None) -> None:
        if self.degraded or self._pool is None:
            self._memory[(scope, key)] = "completed"
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE idempotency_keys
                SET status = 'completed', response_payload = $3::jsonb
                WHERE scope = $1 AND key = $2
                """,
                scope,
                key,
                json.dumps(response_payload or {}, default=str),
            )
