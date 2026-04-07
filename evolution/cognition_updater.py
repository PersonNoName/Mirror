from typing import TYPE_CHECKING

from domain.memory import CapabilityEntry
from domain.evolution import Lesson

if TYPE_CHECKING:
    from core.memory_cache import CoreMemoryCache
    from interfaces.storage import GraphDBInterface
    from core.core_memory_scheduler import CoreMemoryScheduler


class GraphDBInterfaceDummy:
    async def upsert_relation(
        self,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        is_pinned: bool = False,
    ) -> None:
        print(
            f"[GraphDB] upsert: {subject} - {relation} - {object} (conf={confidence})"
        )

    async def get_relation(self, subject: str, object: str) -> dict | None:
        return None


class CoreMemorySchedulerDummy:
    async def write(self, block: str, content, event_id: str | None = None) -> None:
        print(f"[CoreMemorySchedulerDummy] write block={block}")


class CognitionUpdater:
    """
    统一认知进化器：根据 Lesson 类型自动分发到自我认知或世界观更新。
    - capability_issue → 更新自我认知
    - pattern → 更新世界观（写入 Graph DB）
    """

    def __init__(
        self,
        core_memory_cache: "CoreMemoryCache",
        graph_db: "GraphDBInterface",
        core_memory_scheduler: "CoreMemoryScheduler | None" = None,
    ):
        self.core_memory_cache: "CoreMemoryCache" = core_memory_cache
        self._graph_db = graph_db
        self._scheduler = core_memory_scheduler

    async def update(self, lesson: Lesson, user_id: str) -> None:
        if lesson.is_agent_capability_issue:
            await self._update_self_cognition(lesson, user_id)
        elif lesson.is_pattern:
            await self._update_world_model(lesson)
        else:
            print(f"[CognitionUpdater] 未知 lesson 类型，跳过: {lesson.task_id}")

    async def _update_self_cognition(self, lesson: Lesson, user_id: str) -> None:
        core_mem = self.core_memory_cache.get(user_id)
        current = core_mem.self_cognition
        domain = lesson.domain
        entry = current.capability_map.get(domain)

        if entry:
            if lesson.outcome == "done":
                entry.confidence = min(1.0, entry.confidence + 0.05)
            else:
                entry.confidence = max(0.0, entry.confidence - 0.1)
                if lesson.root_cause not in entry.known_limits:
                    entry.known_limits.append(lesson.root_cause)
        else:
            current.capability_map[domain] = CapabilityEntry(
                domain=domain,
                confidence=0.5 if lesson.outcome == "done" else 0.3,
                known_limits=[] if lesson.outcome == "done" else [lesson.root_cause],
            )

        current.version += 1
        core_mem.self_cognition = current
        self.core_memory_cache.set(user_id, core_mem)

        if self._scheduler:
            await self._scheduler.write("self_cognition", current)
        else:
            print("[CognitionUpdater] No scheduler configured, skipping persist")

    async def _update_world_model(self, lesson: Lesson) -> None:
        if not (lesson.subject and lesson.relation and lesson.object):
            print("[CognitionUpdater] Pattern lesson 缺少 subject/relation/object")
            return

        existing = await self._graph_db.get_relation(lesson.subject, lesson.object)
        if existing and self._is_conflict(existing, lesson):
            resolved = await self._resolve_conflict(existing, lesson)
            await self._graph_db.upsert_relation(
                subject=resolved["subject"],
                relation=resolved["relation"],
                object=resolved["object"],
                confidence=resolved["confidence"],
            )
        else:
            await self._graph_db.upsert_relation(
                subject=lesson.subject,
                relation=lesson.relation,
                object=lesson.object,
                confidence=lesson.confidence,
            )

    def _is_conflict(self, existing: dict, lesson: Lesson) -> bool:
        return existing.get("relation") != lesson.relation

    async def _resolve_conflict(self, existing: dict, lesson: Lesson) -> dict:
        existing_conf = existing.get("confidence", 0.5)
        new_conf = lesson.confidence

        if new_conf > existing_conf:
            return {
                "subject": lesson.subject,
                "relation": lesson.relation,
                "object": lesson.object,
                "confidence": new_conf,
            }
        else:
            return {
                "subject": existing["subject"],
                "relation": existing["relation"],
                "object": existing["object"],
                "confidence": existing_conf,
            }
