"""Snapshot helpers for personality rollback."""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from typing import Any


class PersonalitySnapshotStore:
    """Keep a rolling in-memory history of personality states per user."""

    def __init__(self, keep_last: int = 5) -> None:
        self.keep_last = keep_last
        self._snapshots: dict[str, deque[Any]] = defaultdict(lambda: deque(maxlen=self.keep_last))

    async def save(self, user_id: str, personality_state: Any) -> None:
        self._snapshots[user_id].append(deepcopy(personality_state))

    async def latest(self, user_id: str) -> Any | None:
        snapshots = self._snapshots.get(user_id)
        if not snapshots:
            return None
        return deepcopy(snapshots[-1])
