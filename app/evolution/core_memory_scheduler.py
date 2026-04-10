"""Centralized Core Memory write coordinator."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from copy import deepcopy
from typing import Any

from app.evolution.event_bus import EvolutionEntry
from app.memory.core_memory import BehavioralRule, CapabilityEntry, CoreMemory, MemoryEntry, WorldModel
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
                setattr(current, block, await self.rebuild_world_model_snapshot(user_id))
            else:
                setattr(current, block, content)
            current = await self._enforce_budget(user_id, current, block)
            version = getattr(current.self_cognition, "version", 1)
            await self.core_memory_store.save_snapshot(user_id, current, version)
            await self.core_memory_cache.set(user_id, current, version=version)
            return current

    async def rebuild_world_model_snapshot(self, user_id: str) -> WorldModel:
        if self.graph_store is None:
            return WorldModel()
        summary = await self.graph_store.build_world_model_summary(user_id)
        relation_rows = await self.graph_store.query_relations_by_user(user_id, limit=20)
        env_constraints = [
            MemoryEntry(content=f"{item['subject']} {item['relation']} {item['object']}")
            for item in relation_rows
            if item["relation"] == "HAS_CONSTRAINT"
        ]
        user_model = {
            item["object"]: MemoryEntry(content=f"{item['subject']} {item['relation']} {item['object']}")
            for item in relation_rows
            if item["relation"] in {"PREFERS", "DISLIKES"}
        }
        agent_profiles = {
            f"{item['relation']}:{item['object']}": MemoryEntry(content=f"{item['subject']} {item['relation']} {item['object']}")
            for item in relation_rows
            if item["relation"] in {"IS_GOOD_AT", "IS_WEAK_AT", "USES", "KNOWS"}
        }
        social_rules = [MemoryEntry(content=summary)] if summary else []
        return WorldModel(
            env_constraints=env_constraints,
            user_model=user_model,
            agent_profiles=agent_profiles,
            social_rules=social_rules,
        )

    async def _enforce_budget(self, user_id: str, core_memory: CoreMemory, changed_block: str) -> CoreMemory:
        total_used = 0
        for block_name, budget in self.BLOCK_BUDGETS.items():
            block = getattr(core_memory, block_name)
            block_tokens = self._estimate_tokens(block)
            total_used += min(block_tokens, budget)
            if block_tokens > budget:
                setattr(core_memory, block_name, await self._compress_block(user_id, block_name, block, budget))
        if total_used > self.TOTAL_TOKEN_BUDGET:
            setattr(
                core_memory,
                changed_block,
                await self._compress_block(user_id, changed_block, getattr(core_memory, changed_block), self.BLOCK_BUDGETS[changed_block]),
            )
        return core_memory

    async def _compress_block(self, user_id: str, block_name: str, block: Any, target_budget: int) -> Any:
        serialized = json.dumps(block, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        chat = None
        try:
            chat = self.model_registry.chat("lite.extraction")
            payload = [
                {
                    "role": "system",
                    "content": f"压缩以下 {block_name} JSON，保留核心事实与 pinned 项，返回 JSON。",
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
                known_limits=[MemoryEntry(content=item.get("content"), is_pinned=item.get("is_pinned", False)) for item in compressed.get("known_limits", [])],
                mission_clarity=[MemoryEntry(content=item.get("content"), is_pinned=item.get("is_pinned", False)) for item in compressed.get("mission_clarity", [])],
                blindspots=[MemoryEntry(content=item.get("content"), is_pinned=item.get("is_pinned", False)) for item in compressed.get("blindspots", [])],
                version=fallback.version,
            )
        return self._truncate_block(fallback)

    @staticmethod
    def _truncate_block(block: Any) -> Any:
        clone = deepcopy(block)
        for attr in ("known_limits", "mission_clarity", "blindspots", "behavioral_rules", "session_adaptations", "lesson_digest", "env_constraints", "social_rules"):
            if hasattr(clone, attr):
                items = list(getattr(clone, attr))
                pinned = [item for item in items if getattr(item, "is_pinned", False)]
                unpinned = [item for item in items if not getattr(item, "is_pinned", False)]
                setattr(clone, attr, pinned + unpinned[-3:])
        for attr in ("user_model", "agent_profiles", "domain_tips", "agent_habits"):
            if hasattr(clone, attr):
                mapping = dict(getattr(clone, attr))
                trimmed = dict(list(mapping.items())[:5])
                setattr(clone, attr, trimmed)
        return clone

    @staticmethod
    def _estimate_tokens(block: Any) -> int:
        serialized = json.dumps(block, default=lambda o: getattr(o, "__dict__", str(o)), ensure_ascii=False)
        return max(1, len(serialized) // 4)
