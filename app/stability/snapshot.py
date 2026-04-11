"""Snapshot helpers for personality rollback."""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SnapshotRecord:
    """Versioned personality snapshot record."""

    version: int
    created_at: str = field(default_factory=utc_now_iso)
    reason: str = ""
    personality_state: Any = None


class PersonalitySnapshotStore:
    """Keep a rolling in-memory history of personality states per user."""

    def __init__(self, keep_last: int = 5) -> None:
        self.keep_last = keep_last
        self._snapshots: dict[str, deque[SnapshotRecord]] = defaultdict(lambda: deque(maxlen=self.keep_last))

    async def save(self, user_id: str, personality_state: Any, reason: str = "") -> SnapshotRecord:
        version = int(getattr(personality_state, "version", 0))
        record = SnapshotRecord(
            version=version,
            reason=reason,
            personality_state=deepcopy(personality_state),
        )
        self._snapshots[user_id].append(record)
        return deepcopy(record)

    async def latest(self, user_id: str) -> Any | None:
        snapshots = self._snapshots.get(user_id)
        if not snapshots:
            return None
        return deepcopy(snapshots[-1].personality_state)

    async def rollback(self, user_id: str) -> Any | None:
        snapshots = self._snapshots.get(user_id)
        if not snapshots:
            return None
        return deepcopy(snapshots.pop().personality_state)

    async def get_version(self, user_id: str, version: int) -> Any | None:
        snapshots = self._snapshots.get(user_id)
        if not snapshots:
            return None
        for record in reversed(snapshots):
            if record.version == version:
                return deepcopy(record.personality_state)
        return None

    async def list_records(self, user_id: str) -> list[SnapshotRecord]:
        return [deepcopy(record) for record in self._snapshots.get(user_id, deque())]
