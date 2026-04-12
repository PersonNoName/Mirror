"""Dialogue-to-mid-term-memory extraction and promotion."""

from __future__ import annotations

import re
from typing import Any

from app.evolution.event_bus import Event, EventType
from app.tasks.models import Lesson


class MidTermMemoryExtractor:
    """Capture recent cross-session continuity without polluting durable truth."""

    _PROJECT_PATTERNS = (
        re.compile(r"^\s*i(?:'m| am)?\s+(?:currently\s+|still\s+|now\s+)?working on\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*i(?:'m| am)?\s+(?:currently\s+|still\s+|now\s+)?building\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*i(?:'m| am)?\s+(?:currently\s+|still\s+|now\s+)?debugging\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*i(?:'m| am)?\s+(?:currently\s+|still\s+|now\s+)?migrating\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*i(?:'m| am)?\s+(?:currently\s+|still\s+|now\s+)?refactoring\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*\u6211(?:\u6700\u8fd1|\u73b0\u5728|\u8fd8\u5728)?(?:\u5728\u505a|\u6b63\u5728\u505a)(?P<topic>.+)$"),
        re.compile(r"^\s*\u6211(?:\u6700\u8fd1|\u73b0\u5728|\u8fd8\u5728)?(?:\u5728\u5199|\u6b63\u5728\u5199)(?P<topic>.+)$"),
        re.compile(r"^\s*\u6211(?:\u6700\u8fd1|\u73b0\u5728|\u8fd8\u5728)?(?:\u5728\u8c03\u8bd5|\u6b63\u5728\u8c03\u8bd5)(?P<topic>.+)$"),
        re.compile(r"^\s*\u6211(?:\u6700\u8fd1|\u73b0\u5728|\u8fd8\u5728)?(?:\u5728\u91cd\u6784|\u6b63\u5728\u91cd\u6784)(?P<topic>.+)$"),
        re.compile(r"^\s*\u6211(?:\u6700\u8fd1|\u73b0\u5728|\u8fd8\u5728)?(?:\u5728\u8fc1\u79fb|\u6b63\u5728\u8fc1\u79fb)(?P<topic>.+)$"),
    )
    _GOAL_PATTERNS = (
        re.compile(r"^\s*i want to\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*i need to\s+(?P<topic>.+)$", re.I),
        re.compile(r"^\s*\u6211\u60f3(?P<topic>.+)$"),
        re.compile(r"^\s*\u6211\u9700\u8981(?P<topic>.+)$"),
        re.compile(r"^\s*\u6211\u8ba1\u5212(?P<topic>.+)$"),
    )

    def __init__(
        self,
        *,
        mid_term_memory_store: Any,
        event_bus: Any | None = None,
        memory_governance_service: Any | None = None,
        vector_retriever: Any | None = None,
    ) -> None:
        self.mid_term_memory_store = mid_term_memory_store
        self.event_bus = event_bus
        self.memory_governance_service = memory_governance_service
        self.vector_retriever = vector_retriever

    async def handle_dialogue_ended(self, event: Event) -> None:
        user_id = str(event.payload.get("user_id", "")).strip()
        session_id = str(event.payload.get("session_id", "")).strip()
        text = str(event.payload.get("text", "")).strip()
        if not user_id or not text:
            return
        for candidate in self._extract_candidates(text):
            if self.memory_governance_service is not None:
                current = await self.memory_governance_service.core_memory_cache.get(user_id)
                if self.memory_governance_service.is_blocked(current.world_model, "fact"):
                    continue
            item = await self.mid_term_memory_store.upsert_observation(
                user_id=user_id,
                session_id=session_id,
                topic_key=str(candidate["topic_key"]),
                content=str(candidate["content"]),
                memory_type=str(candidate["memory_type"]),
                source="dialogue_mid_term",
                confidence=float(candidate.get("confidence", 0.65)),
                event_id=event.id,
                metadata={"source_text": text, "session_id": session_id},
            )
            if self.vector_retriever is not None:
                try:
                    await self.vector_retriever.upsert(
                        user_id=user_id,
                        namespace="mid_term_memory",
                        content=item.content,
                        metadata={"memory_key": item.memory_key, "topic_key": item.topic_key, "memory_type": item.memory_type},
                        truth_type="mid_term",
                        status=item.status,
                        confirmed_by_user=False,
                    )
                except Exception:
                    pass
            promoted = await self.mid_term_memory_store.maybe_promote(user_id=user_id, memory_key=item.memory_key)
            if promoted is not None and self.event_bus is not None:
                await self.event_bus.emit(
                    Event(
                        type=EventType.LESSON_GENERATED,
                        payload={"lesson": self._lesson_payload(event, promoted)},
                    )
                )

    @classmethod
    def _extract_candidates(cls, text: str) -> list[dict[str, Any]]:
        normalized = text.strip()
        if len(normalized) < 6 or len(normalized) > 240:
            return []
        candidates: list[dict[str, Any]] = []
        for pattern in cls._PROJECT_PATTERNS:
            match = pattern.match(normalized)
            if match:
                topic = cls._sanitize_topic(match.group("topic"))
                if topic:
                    candidates.append(
                        {
                            "topic_key": topic.lower(),
                            "content": f"User is working on {topic}.",
                            "memory_type": "project",
                            "confidence": 0.72,
                        }
                    )
                return candidates
        for pattern in cls._GOAL_PATTERNS:
            match = pattern.match(normalized)
            if match:
                topic = cls._sanitize_topic(match.group("topic"))
                if topic:
                    candidates.append(
                        {
                            "topic_key": topic.lower(),
                            "content": f"User wants to {topic}.",
                            "memory_type": "goal",
                            "confidence": 0.68,
                        }
                    )
                return candidates
        if any(token in normalized.lower() for token in ("project", "migration", "refactor", "bug", "feature")):
            candidates.append(
                {
                    "topic_key": cls._sanitize_topic(normalized).lower(),
                    "content": cls._truncate(normalized),
                    "memory_type": "topic",
                    "confidence": 0.58,
                }
            )
        return candidates[:1]

    @staticmethod
    def _sanitize_topic(value: str) -> str:
        topic = str(value or "").strip(" .,!?:;，。！？；：")
        return MidTermMemoryExtractor._truncate(topic, limit=120)

    @staticmethod
    def _truncate(value: str, *, limit: int = 180) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3].rstrip()}..."

    @staticmethod
    def _lesson_payload(event: Event, item: Any) -> dict[str, Any]:
        lesson = Lesson(
            source_task_id=event.id,
            user_id=str(event.payload.get("user_id", "")),
            domain="mid_term_topic",
            outcome="observed",
            category="mid_term_promotion",
            summary=item.content,
            lesson_text=item.content,
            confidence=min(max(float(getattr(item, "strength", 0.72)), 0.62), 0.8),
            details={
                "source": "mid_term_memory",
                "mid_term_memory_key": item.memory_key,
                "mid_term_memory_type": item.memory_type,
                "session_id": str(event.payload.get("session_id", "")),
                "memory_tier": "mid_term_promotion",
                "explicit_user_statement": False,
                "explicit_user_confirmation": False,
            },
        )
        return {
            "id": lesson.id,
            "source_task_id": lesson.source_task_id,
            "user_id": lesson.user_id,
            "domain": lesson.domain,
            "outcome": lesson.outcome,
            "category": lesson.category,
            "summary": lesson.summary,
            "root_cause": lesson.root_cause,
            "lesson_text": lesson.lesson_text,
            "is_agent_capability_issue": lesson.is_agent_capability_issue,
            "subject": lesson.subject,
            "relation": lesson.relation,
            "object": lesson.object,
            "details": lesson.details,
            "confidence": lesson.confidence,
            "created_at": lesson.created_at,
        }
