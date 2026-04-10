"""Async observer engine for dialogue knowledge extraction."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.evolution.event_bus import Event, EventType
from app.evolution.helpers import extract_json
from app.providers.openai_compat import ProviderRequestError


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
        self._aliases = {"pyhton": "Python", "vsc": "VSCode", "vscode": "VSCode"}

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
        last = events[-1]
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
                        "从对话中抽取 JSON 数组三元组。关系仅允许 "
                        "PREFERS / DISLIKES / USES / KNOWS / HAS_CONSTRAINT / IS_GOOD_AT / IS_WEAK_AT。"
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
        return aligned
