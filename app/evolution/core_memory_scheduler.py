"""Centralized Core Memory write coordinator."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from copy import deepcopy
from typing import Any

from app.memory.core_memory import (
    CoreMemory,
    DurableMemory,
    FactualMemory,
    InferredMemory,
    MemoryEntry,
    RelationshipMemory,
    WorldModel,
)
from app.providers.openai_compat import ProviderRequestError


class CoreMemoryScheduler:
    """Serialize core-memory writes and enforce approximate budget limits."""

    TOTAL_TOKEN_BUDGET = 5000
    BLOCK_BUDGETS = {
        "self_cognition": 1000,
        "world_model": 1000,
        "personality": 800,
        "task_experience": 1200,
    }
    DYNAMIC_RESERVE = 1000

    def __init__(
        self,
        *,
        core_memory_store: Any,
        core_memory_cache: Any,
        graph_store: Any | None,
        model_registry: Any,
        circuit_breaker: Any | None = None,
    ) -> None:
        self.core_memory_store = core_memory_store
        self.core_memory_cache = core_memory_cache
        self.graph_store = graph_store
        self.model_registry = model_registry
        self.circuit_breaker = circuit_breaker
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def write(self, user_id: str, block: str, content: Any, event_id: str | None = None) -> CoreMemory:
        async with self._locks[user_id]:
            current = deepcopy(await self.core_memory_cache.get(user_id))
            if block == "world_model":
                base_world_model = content if isinstance(content, WorldModel) else current.world_model
                setattr(current, block, await self.rebuild_world_model_snapshot(user_id, base_world_model))
            else:
                setattr(current, block, content)
            current = await self._enforce_budget(user_id, current, block)
            version = max(
                int(getattr(current.self_cognition, "version", 1)),
                int(getattr(current.personality, "version", 1)),
            )
            await self.core_memory_store.save_snapshot(user_id, current, version)
            await self.core_memory_cache.set(user_id, current, version=version)
            return current

    async def rebuild_world_model_snapshot(
        self,
        user_id: str,
        base_world_model: WorldModel | None = None,
    ) -> WorldModel:
        world_model = deepcopy(base_world_model or WorldModel())
        if self.graph_store is None:
            return world_model

        relationship_rows = await self.graph_store.query_relations_by_user(user_id, limit=50)
        relationship_history: list[RelationshipMemory] = []
        pending_confirmations = list(world_model.pending_confirmations)
        memory_conflicts = list(world_model.memory_conflicts)

        for row in relationship_rows:
            item = RelationshipMemory(
                content=f"{row['subject']} {row['relation']} {row['object']}",
                source=str(row.get("source", "graph")),
                confidence=float(row.get("confidence", 0.0)),
                updated_at=str(row.get("updated_at", "")),
                confirmed_by_user=bool(row.get("confirmed_by_user", False)),
                truth_type="relationship",
                time_horizon=row.get("time_horizon", "long_term"),
                status=row.get("status", "active"),
                sensitivity=row.get("sensitivity", "normal"),
                memory_key=(
                    f"relationship:{row['subject']}:{row['relation']}:{row['object']}:{row.get('updated_at', '')}"
                ),
                conflict_with=list(row.get("conflict_with", [])),
                metadata=dict(row.get("metadata", {})),
                subject=str(row.get("subject", "")),
                relation=str(row.get("relation", "")),
                object=str(row.get("object", "")),
            )
            relationship_history.append(item)
            if item.status == "pending_confirmation":
                pending_confirmations.append(item)
            elif item.status == "conflicted":
                memory_conflicts.append(item)

        world_model.relationship_history = relationship_history
        world_model.pending_confirmations = self._dedupe_memories(pending_confirmations)
        world_model.memory_conflicts = self._dedupe_memories(memory_conflicts)
        return world_model

    async def _enforce_budget(self, user_id: str, core_memory: CoreMemory, changed_block: str) -> CoreMemory:
        total_used = 0
        for block_name, budget in self.BLOCK_BUDGETS.items():
            block = getattr(core_memory, block_name)
            block_tokens = self._estimate_tokens(block)
            total_used += min(block_tokens, budget)
            if block_tokens > budget:
                setattr(core_memory, block_name, await self._compress_block(block_name, block))
        if total_used > self.TOTAL_TOKEN_BUDGET:
            setattr(
                core_memory,
                changed_block,
                await self._compress_block(changed_block, getattr(core_memory, changed_block)),
            )
        return core_memory

    async def _compress_block(self, block_name: str, block: Any) -> Any:
        serialized = json.dumps(block, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        try:
            chat = self.model_registry.chat("lite.extraction")
            payload = [
                {
                    "role": "system",
                    "content": (
                        f"Compress the following {block_name} JSON while preserving pinned items, "
                        "confirmed facts, pending confirmations, and conflict summaries. Return JSON only."
                    ),
                },
                {"role": "user", "content": serialized},
            ]
            if self.circuit_breaker is None:
                response = await chat.generate(payload)
            else:
                response = await self.circuit_breaker.call("evolution_lite_extraction", chat.generate, payload)
            from app.evolution.helpers import extract_json

            compressed = extract_json(response, None)
            if compressed is not None:
                return self._coerce_block(block_name, compressed, block)
        except (ProviderRequestError, Exception):
            pass
        return self._truncate_block(block)

    def _coerce_block(self, block_name: str, compressed: Any, fallback: Any) -> Any:
        if not isinstance(compressed, dict):
            return self._truncate_block(fallback)
        if block_name == "self_cognition":
            return fallback.__class__(
                capability_map=fallback.capability_map,
                known_limits=[
                    MemoryEntry(content=item.get("content"), is_pinned=item.get("is_pinned", False))
                    for item in compressed.get("known_limits", [])
                ],
                mission_clarity=[
                    MemoryEntry(content=item.get("content"), is_pinned=item.get("is_pinned", False))
                    for item in compressed.get("mission_clarity", [])
                ],
                blindspots=[
                    MemoryEntry(content=item.get("content"), is_pinned=item.get("is_pinned", False))
                    for item in compressed.get("blindspots", [])
                ],
                version=fallback.version,
            )
        if block_name == "world_model":
            return WorldModel(
                confirmed_facts=[
                    self._coerce_durable_item(item, FactualMemory)
                    for item in compressed.get("confirmed_facts", [])
                ],
                inferred_memories=[
                    self._coerce_durable_item(item, InferredMemory)
                    for item in compressed.get("inferred_memories", [])
                ],
                relationship_history=[
                    self._coerce_relationship_item(item)
                    for item in compressed.get("relationship_history", [])
                ],
                pending_confirmations=[
                    self._coerce_durable_item(item)
                    for item in compressed.get("pending_confirmations", [])
                ],
                memory_conflicts=[
                    self._coerce_durable_item(item)
                    for item in compressed.get("memory_conflicts", [])
                ],
            )
        return self._truncate_block(fallback)

    @staticmethod
    def _truncate_block(block: Any) -> Any:
        clone = deepcopy(block)
        if hasattr(clone, "core_personality"):
            rules = list(clone.core_personality.behavioral_rules)
            clone.core_personality.behavioral_rules = rules[:4]
            clone.session_adaptation.current_items = list(clone.session_adaptation.current_items)[:3]
            if len(clone.snapshot_refs) > 3:
                clone.snapshot_refs = list(clone.snapshot_refs)[:3]
            return clone
        for attr in (
            "known_limits",
            "mission_clarity",
            "blindspots",
            "behavioral_rules",
            "session_adaptations",
            "lesson_digest",
            "confirmed_facts",
            "inferred_memories",
            "relationship_history",
            "pending_confirmations",
            "memory_conflicts",
        ):
            if not hasattr(clone, attr):
                continue
            items = list(getattr(clone, attr))
            if attr in {"pending_confirmations", "memory_conflicts"}:
                setattr(clone, attr, items[:2])
                continue
            prioritized = sorted(
                items,
                key=lambda item: (
                    0 if getattr(item, "confirmed_by_user", False) else 1,
                    0 if getattr(item, "is_pinned", False) else 1,
                    0 if getattr(item, "status", "active") == "active" else 1,
                ),
            )
            setattr(clone, attr, prioritized[:4])
        for attr in ("domain_tips", "agent_habits"):
            if hasattr(clone, attr):
                mapping = dict(getattr(clone, attr))
                setattr(clone, attr, dict(list(mapping.items())[:5]))
        return clone

    @staticmethod
    def _estimate_tokens(block: Any) -> int:
        serialized = json.dumps(block, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        return max(1, len(serialized) // 4)

    @staticmethod
    def _coerce_durable_item(data: dict[str, Any], cls: type[DurableMemory] = DurableMemory) -> DurableMemory:
        return cls(
            content=str(data.get("content", "")),
            source=str(data.get("source", "compression")),
            confidence=float(data.get("confidence", 0.0)),
            updated_at=str(data.get("updated_at", "")),
            confirmed_by_user=bool(data.get("confirmed_by_user", False)),
            is_pinned=bool(data.get("is_pinned", False)),
            truth_type=data.get("truth_type", "fact"),
            time_horizon=data.get("time_horizon", "long_term"),
            status=data.get("status", "active"),
            sensitivity=data.get("sensitivity", "normal"),
            memory_key=str(data.get("memory_key", "")),
            conflict_with=list(data.get("conflict_with", [])),
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def _coerce_relationship_item(cls, data: dict[str, Any]) -> RelationshipMemory:
        base = cls._coerce_durable_item(data, RelationshipMemory)
        return RelationshipMemory(
            content=base.content,
            source=base.source,
            confidence=base.confidence,
            updated_at=base.updated_at,
            confirmed_by_user=base.confirmed_by_user,
            is_pinned=base.is_pinned,
            truth_type="relationship",
            time_horizon=base.time_horizon,
            status=base.status,
            sensitivity=base.sensitivity,
            memory_key=base.memory_key,
            conflict_with=base.conflict_with,
            metadata=base.metadata,
            subject=str(data.get("subject", "")),
            relation=str(data.get("relation", "")),
            object=str(data.get("object", "")),
        )

    @staticmethod
    def _dedupe_memories(items: list[DurableMemory]) -> list[DurableMemory]:
        deduped: dict[str, DurableMemory] = {}
        for item in items:
            key = item.memory_key or item.content
            existing = deduped.get(key)
            if existing is None or item.updated_at >= existing.updated_at:
                deduped[key] = item
        return list(deduped.values())
