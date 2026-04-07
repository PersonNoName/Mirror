import asyncpg

from domain.stability import SnapshotRecord
from interfaces.storage import SnapshotStoreInterface


_SNAPSHOT_TABLE = """
CREATE TABLE IF NOT EXISTS snapshots (
    id TEXT PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    block_type TEXT NOT NULL,
    version INTEGER NOT NULL,
    content JSONB NOT NULL DEFAULT '{}',
    reason TEXT
)
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_snapshots_block_type ON snapshots(block_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp DESC);
"""


class PostgresSnapshotStore(SnapshotStoreInterface):
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def initialize(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_SNAPSHOT_TABLE)
            await conn.execute(_CREATE_INDEXES)

    async def save(self, snapshot: SnapshotRecord) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO snapshots (id, timestamp, block_type, version, content, reason)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                snapshot.id,
                snapshot.timestamp,
                snapshot.block_type,
                snapshot.version,
                snapshot.content,
                snapshot.reason,
            )

    async def get_latest(self, block_type: str) -> SnapshotRecord | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM snapshots
                WHERE block_type = $1
                ORDER BY version DESC
                LIMIT 1
                """,
                block_type,
            )
            return self._row_to_record(row) if row else None

    async def get_history(
        self, block_type: str, limit: int = 5
    ) -> list[SnapshotRecord]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM snapshots
                WHERE block_type = $1
                ORDER BY version DESC
                LIMIT $2
                """,
                block_type,
                limit,
            )
            return [self._row_to_record(row) for row in rows]

    def _row_to_record(self, row: asyncpg.Record) -> SnapshotRecord:
        return SnapshotRecord(
            id=row["id"],
            timestamp=row["timestamp"],
            block_type=row["block_type"],
            version=row["version"],
            content=row["content"] or {},
            reason=row["reason"],
        )
