"""Persistent evolution journal."""

from __future__ import annotations

import json
from typing import Any

try:
    import asyncpg
except ImportError:  # pragma: no cover
    asyncpg = None

from app.config import settings
from app.evolution.event_bus import EvolutionEntry


class EvolutionJournal:
    """Append-only evolution journal with memory fallback."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres.dsn
        self._pool: Any | None = None
        self._memory: list[EvolutionEntry] = []
        self.degraded = asyncpg is None

    async def initialize(self) -> None:
        if asyncpg is None:
            self.degraded = True
            return
        try:
            self._pool = await asyncpg.create_pool(dsn=self.dsn)
        except Exception:
            self.degraded = True

    async def record(self, entry: EvolutionEntry) -> None:
        self._memory.append(entry)
        if self.degraded or self._pool is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evolution_journal (id, user_id, event_type, summary, details, created_at)
                VALUES ($1, $2, $3, $4, $5::jsonb, $6)
                ON CONFLICT (id) DO NOTHING
                """,
                entry.id,
                entry.user_id,
                entry.event_type,
                entry.summary,
                json.dumps(entry.details),
                entry.created_at,
            )

    async def list_recent(self, limit: int = 20, user_id: str | None = None) -> list[EvolutionEntry]:
        if self.degraded or self._pool is None:
            items = [item for item in self._memory if user_id is None or item.user_id == user_id]
            return list(reversed(items[-limit:]))
        query = """
            SELECT id, user_id, event_type, summary, details, created_at
            FROM evolution_journal
        """
        params: list[Any] = []
        if user_id is not None:
            query += " WHERE user_id = $1"
            params.append(user_id)
        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
        entries: list[EvolutionEntry] = []
        for row in rows:
            details = row["details"]
            if isinstance(details, str):
                details = json.loads(details)
            entries.append(
                EvolutionEntry(
                    id=str(row["id"]),
                    user_id=row["user_id"],
                    event_type=row["event_type"],
                    summary=row["summary"],
                    details=dict(details or {}),
                    created_at=row["created_at"],
                )
            )
        return entries
