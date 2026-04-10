"""Cognition updater for lessons."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.memory.core_memory import CapabilityEntry, MemoryEntry
from app.tasks.models import Lesson


class CognitionUpdater:
    """Update self-cognition or world-model based on lessons."""

    def __init__(self, *, core_memory_cache: Any, core_memory_scheduler: Any, graph_store: Any | None) -> None:
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.graph_store = graph_store
        self._last_updated: dict[str, datetime] = {}

    async def handle_lesson_generated(self, event: Any) -> None:
        lesson = Lesson(**event.payload["lesson"])
        if not self._should_run(lesson.user_id):
            return
        if lesson.is_agent_capability_issue:
            await self._update_self_cognition(lesson)
        else:
            await self._update_world_model(lesson)
        self._last_updated[lesson.user_id] = datetime.now(timezone.utc)

    def _should_run(self, user_id: str) -> bool:
        last = self._last_updated.get(user_id)
        if last is None:
            return True
        return (datetime.now(timezone.utc) - last).total_seconds() >= 600

    async def _update_self_cognition(self, lesson: Lesson) -> None:
        current = await self.core_memory_cache.get(lesson.user_id)
        block = current.self_cognition
        domain = lesson.domain or "general"
        entry = block.capability_map.get(domain)
        if entry is None:
            entry = CapabilityEntry(description=f"{domain} capability", confidence=0.5 if lesson.outcome == "done" else 0.3)
            block.capability_map[domain] = entry
        if lesson.outcome == "done":
            entry.confidence = min(1.0, entry.confidence + 0.05)
        else:
            entry.confidence = max(0.0, entry.confidence - 0.1)
            if lesson.root_cause and lesson.root_cause not in entry.limitations:
                entry.limitations.append(lesson.root_cause)
        if lesson.root_cause:
            block.known_limits.append(MemoryEntry(content=lesson.root_cause))
        block.version += 1
        await self.core_memory_scheduler.write(lesson.user_id, "self_cognition", block, event_id=lesson.id)

    async def _update_world_model(self, lesson: Lesson) -> None:
        if self.graph_store is not None and lesson.subject and lesson.relation and lesson.object:
            await self.graph_store.upsert_relation(
                user_id=lesson.user_id,
                subject=lesson.subject,
                relation=lesson.relation,
                object=lesson.object,
                confidence=lesson.confidence or 0.7,
                metadata={"source": "lesson"},
            )
        await self.core_memory_scheduler.write(lesson.user_id, "world_model", None, event_id=lesson.id)
