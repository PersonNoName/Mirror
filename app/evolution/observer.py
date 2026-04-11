"""Async observer engine for dialogue knowledge extraction."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.evolution.event_bus import Event, EventType
from app.evolution.helpers import extract_json
from app.providers.openai_compat import ProviderRequestError
from app.tasks.models import Lesson


class ObserverEngine:
    """Batch dialogue events and extract durable triples."""

    BATCH_WINDOW_SECONDS = 30
    MAX_BATCH_SIZE = 5

    def __init__(self, *, model_registry: Any, graph_store: Any | None, vector_retriever: Any | None, event_bus: Any) -> None:
        self.model_registry = model_registry
        self.graph_store = graph_store
        self.vector_retriever = vector_retriever
        self.event_bus = event_bus
        self.circuit_breaker: Any | None = None
        self._pending: dict[str, list[Event]] = defaultdict(list)
        self._flush_tasks: dict[str, asyncio.Task[None]] = {}
        self._aliases = {"pyhton": "Python", "py": "Python", "python": "Python", "vsc": "VSCode", "vscode": "VSCode"}

    async def handle_dialogue_ended(self, event: Event) -> None:
        user_id = event.payload.get("user_id", "")
        self._pending[user_id].append(event)
        if len(self._pending[user_id]) >= self.MAX_BATCH_SIZE:
            await self._flush(user_id)
            return
        if user_id not in self._flush_tasks or self._flush_tasks[user_id].done():
            self._flush_tasks[user_id] = asyncio.create_task(self._delayed_flush(user_id))

    async def _delayed_flush(self, user_id: str) -> None:
        await asyncio.sleep(self.BATCH_WINDOW_SECONDS)
        await self._flush(user_id)

    async def _flush(self, user_id: str) -> None:
        events = self._pending.pop(user_id, [])
        if not events:
            return
        dialogue = "\n".join(f"user: {e.payload.get('text', '')}\nassistant: {e.payload.get('reply', '')}" for e in events)
        triples = await self._extract_triples(dialogue)
        last = events[-1]
        for triple in triples:
            aligned = self._align_triple(triple)
            if self.graph_store is not None:
                await self.graph_store.upsert_relation(
                    user_id=user_id,
                    subject=aligned["subject"],
                    relation=aligned["relation"],
                    object=aligned["object"],
                    confidence=float(aligned.get("confidence", 0.7)),
                    metadata={"source": "observer"},
                )
            if self.vector_retriever is not None:
                await self.vector_retriever.upsert(
                    user_id=user_id,
                    namespace="dialogue_fragment",
                    content=f'{aligned["subject"]} {aligned["relation"]} {aligned["object"]}',
                    metadata={"confidence": aligned.get("confidence", 0.7)},
                )
            lesson = self._triple_to_lesson(last, aligned)
            if lesson is not None:
                await self.event_bus.emit(
                    Event(
                        type=EventType.LESSON_GENERATED,
                        payload={"lesson": self._lesson_payload(lesson)},
                    )
                )
        await self.event_bus.emit(
            Event(
                type=EventType.OBSERVATION_DONE,
                payload={
                    "user_id": user_id,
                    "session_id": last.payload.get("session_id", ""),
                    "triples": triples,
                    "dialogue": dialogue,
                },
            )
        )

    async def _extract_triples(self, dialogue: str) -> list[dict[str, Any]]:
        if not dialogue:
            return []
        try:
            generate = self.model_registry.chat("lite.extraction").generate
            payload = [
                {
                    "role": "system",
                    "content": (
                        "Extract a JSON array of durable user triples from the dialogue. "
                        "Only extract facts the user explicitly stated about themselves. "
                        "Use subject='user' for the user. "
                        "Allowed relations only: PREFERS, DISLIKES, USES, KNOWS, HAS_CONSTRAINT, IS_GOOD_AT, IS_WEAK_AT. "
                        "Each item must be an object with subject, relation, object, and confidence. "
                        "If there is no durable explicit user fact, return []."
                    ),
                },
                {"role": "user", "content": dialogue},
            ]
            if self.circuit_breaker is None:
                response = await generate(payload)
            else:
                response = await self.circuit_breaker.call("evolution_lite_extraction", generate, payload)
        except (ProviderRequestError, KeyError, NotImplementedError, ValueError):
            return []
        triples = extract_json(response, [])
        return [item for item in triples if isinstance(item, dict) and item.get("subject") and item.get("relation") and item.get("object")]

    def _align_triple(self, triple: dict[str, Any]) -> dict[str, Any]:
        aligned = dict(triple)
        for side in ("subject", "object"):
            value = str(aligned.get(side, "")).strip()
            canonical = self._aliases.get(value.lower(), value)
            aligned[side] = canonical
        aligned["relation"] = str(aligned.get("relation", "")).strip().upper()
        return aligned

    @staticmethod
    def _triple_to_lesson(event: Event, triple: dict[str, Any]) -> Lesson | None:
        subject = str(triple.get("subject", "")).strip().lower()
        relation = str(triple.get("relation", "")).strip().upper()
        object_value = str(triple.get("object", "")).strip()
        if subject not in {"user", "the user"} or not object_value:
            return None
        relation_map = {
            "PREFERS": "prefers",
            "DISLIKES": "dislikes",
            "USES": "uses",
        }
        preference_relation = relation_map.get(relation)
        if preference_relation is None:
            return None
        summary = f"User {preference_relation} {object_value}."
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="explicit_preference",
            outcome="observed",
            category="observer_explicit_preference",
            summary=summary,
            lesson_text=summary,
            details={
                "source": "observer_triple",
                "session_id": event.payload.get("session_id", ""),
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "preference_relation": preference_relation,
                "preference_object": object_value,
            },
            confidence=float(triple.get("confidence", 0.85)),
        )

    @staticmethod
    def _lesson_payload(lesson: Lesson) -> dict[str, Any]:
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
        }
