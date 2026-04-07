import asyncpg

from domain.evolution import EvolutionEntry
from interfaces.storage import JournalStoreInterface


_JOURNAL_TABLE = """
CREATE TABLE IF NOT EXISTS evolution_journal (
    id TEXT PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    type TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}',
    session_id TEXT
)
"""


class PostgresJournalStore(JournalStoreInterface):
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def initialize(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_JOURNAL_TABLE)

    async def append(self, entry: EvolutionEntry) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evolution_journal (id, timestamp, type, summary, detail, session_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                entry.id,
                entry.timestamp,
                entry.type,
                entry.summary,
                entry.detail,
                entry.session_id,
            )

    async def get_recent(self, last_n: int) -> list[EvolutionEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM evolution_journal
                ORDER BY timestamp DESC
                LIMIT $1
                """,
                last_n,
            )
            return [self._row_to_entry(row) for row in rows]

    async def get_by_session(self, session_id: str) -> list[EvolutionEntry]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM evolution_journal
                WHERE session_id = $1
                ORDER BY timestamp ASC
                """,
                session_id,
            )
            return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: asyncpg.Record) -> EvolutionEntry:
        return EvolutionEntry(
            id=row["id"],
            timestamp=row["timestamp"],
            type=row["type"],
            summary=row["summary"],
            detail=row["detail"] or {},
            session_id=row["session_id"],
        )
