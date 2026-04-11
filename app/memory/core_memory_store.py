"""PostgreSQL-backed storage for core memory snapshots."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import asyncpg

from app.config import settings
from app.memory.core_memory import (
    BehavioralRule,
    CapabilityEntry,
    CorePersonality,
    CoreMemory,
    DurableMemory,
    FactualMemory,
    InferredMemory,
    MemoryEntry,
    PersonalityState,
    RelationshipStyle,
    RelationshipMemory,
    SessionAdaptation,
    SelfCognition,
    TaskExperience,
    WorldModel,
)


def _memory_entry_from_dict(data: dict[str, Any]) -> MemoryEntry:
    return MemoryEntry(
        content=data.get("content"),
        is_pinned=bool(data.get("is_pinned", False)),
    )


def _durable_memory_from_dict(data: dict[str, Any], cls: type[DurableMemory] = DurableMemory) -> DurableMemory:
    return cls(
        content=str(data.get("content", "")),
        source=str(data.get("source", "legacy")),
        confidence=float(data.get("confidence", 0.0)),
        updated_at=str(data.get("updated_at", "")) or "",
        confirmed_by_user=bool(data.get("confirmed_by_user", False)),
        is_pinned=bool(data.get("is_pinned", False)),
        truth_type=data.get("truth_type", getattr(cls, "truth_type", "fact")),
        time_horizon=data.get("time_horizon", "long_term"),
        status=data.get("status", "active"),
        sensitivity=data.get("sensitivity", "normal"),
        memory_key=str(data.get("memory_key", "")),
        conflict_with=list(data.get("conflict_with", [])),
        metadata=dict(data.get("metadata", {})),
    )


def _relationship_memory_from_dict(data: dict[str, Any]) -> RelationshipMemory:
    item = _durable_memory_from_dict(data, RelationshipMemory)
    return RelationshipMemory(
        content=item.content,
        source=item.source,
        confidence=item.confidence,
        updated_at=item.updated_at,
        confirmed_by_user=item.confirmed_by_user,
        is_pinned=item.is_pinned,
        truth_type="relationship",
        time_horizon=item.time_horizon,
        status=item.status,
        sensitivity=item.sensitivity,
        memory_key=item.memory_key,
        conflict_with=item.conflict_with,
        metadata=item.metadata,
        subject=str(data.get("subject", "")),
        relation=str(data.get("relation", "")),
        object=str(data.get("object", "")),
    )


def _capability_entry_from_dict(data: dict[str, Any]) -> CapabilityEntry:
    return CapabilityEntry(
        description=data.get("description", ""),
        confidence=float(data.get("confidence", 0.0)),
        limitations=list(data.get("limitations", [])),
        evidence=list(data.get("evidence", [])),
        metadata=dict(data.get("metadata", {})),
    )


def _behavioral_rule_from_dict(data: dict[str, Any]) -> BehavioralRule:
    return BehavioralRule(
        rule=data.get("rule", ""),
        rationale=data.get("rationale", ""),
        priority=int(data.get("priority", 1)),
        source=data.get("source", "system"),
        confidence=float(data.get("confidence", 0.0)),
        is_pinned=bool(data.get("is_pinned", False)),
        metadata=dict(data.get("metadata", {})),
    )


def _core_personality_from_dict(data: dict[str, Any]) -> CorePersonality:
    return CorePersonality(
        baseline_description=str(data.get("baseline_description", "")),
        behavioral_rules=[
            _behavioral_rule_from_dict(item)
            for item in list(data.get("behavioral_rules", []))
        ],
        traits_internal={
            key: float(value)
            for key, value in dict(data.get("traits_internal", {})).items()
        },
        version=int(data.get("version", 1)),
        updated_at=str(data.get("updated_at", "")),
        stable_fields=list(
            data.get(
                "stable_fields",
                ["baseline_description", "behavioral_rules", "traits_internal"],
            )
        ),
    )


def _relationship_style_from_dict(data: dict[str, Any]) -> RelationshipStyle:
    return RelationshipStyle(
        warmth=float(data.get("warmth", 0.5)),
        boundary_strength=float(data.get("boundary_strength", 0.8)),
        supportiveness=float(data.get("supportiveness", 0.6)),
        humor=float(data.get("humor", 0.3)),
        preferred_closeness=str(data.get("preferred_closeness", "steady")),
        updated_at=str(data.get("updated_at", "")),
    )


def _session_adaptation_from_dict(data: dict[str, Any]) -> SessionAdaptation:
    return SessionAdaptation(
        current_items=list(data.get("current_items", [])),
        session_id=str(data.get("session_id", "")),
        created_at=str(data.get("created_at", "")),
        expires_at=str(data.get("expires_at", "")),
        max_items=int(data.get("max_items", 5)),
    )


def _legacy_world_model_items_to_facts(items: list[dict[str, Any]], section: str) -> list[FactualMemory]:
    facts: list[FactualMemory] = []
    for index, item in enumerate(items):
        entry = _memory_entry_from_dict(item)
        facts.append(
            FactualMemory(
                content=str(entry.content),
                source="legacy_snapshot",
                confirmed_by_user=True,
                is_pinned=entry.is_pinned,
                memory_key=f"{section}:{index}",
                metadata={"legacy_section": section},
            )
        )
    return facts


def _legacy_mapping_to_facts(items: dict[str, dict[str, Any]], section: str) -> list[FactualMemory]:
    facts: list[FactualMemory] = []
    for key, raw in items.items():
        entry = _memory_entry_from_dict(raw)
        facts.append(
            FactualMemory(
                content=str(entry.content),
                source="legacy_snapshot",
                confirmed_by_user=True,
                is_pinned=entry.is_pinned,
                memory_key=f"{section}:{key}",
                metadata={"legacy_section": section, "label": key},
            )
        )
    return facts


def _core_memory_from_dict(data: dict[str, Any]) -> CoreMemory:
    self_cognition = data.get("self_cognition", {})
    world_model = data.get("world_model", {})
    personality = data.get("personality", {})
    task_experience = data.get("task_experience", {})

    return CoreMemory(
        self_cognition=SelfCognition(
            capability_map={
                key: _capability_entry_from_dict(value)
                for key, value in dict(self_cognition.get("capability_map", {})).items()
            },
            known_limits=[
                _memory_entry_from_dict(item)
                for item in list(self_cognition.get("known_limits", []))
            ],
            mission_clarity=[
                _memory_entry_from_dict(item)
                for item in list(self_cognition.get("mission_clarity", []))
            ],
            blindspots=[
                _memory_entry_from_dict(item)
                for item in list(self_cognition.get("blindspots", []))
            ],
            version=int(self_cognition.get("version", 1)),
        ),
        world_model=WorldModel(
            confirmed_facts=[
                _durable_memory_from_dict(item, FactualMemory)
                for item in list(world_model.get("confirmed_facts", []))
            ]
            or (
                _legacy_world_model_items_to_facts(list(world_model.get("env_constraints", [])), "env_constraints")
                + _legacy_mapping_to_facts(dict(world_model.get("user_model", {})), "user_model")
                + _legacy_mapping_to_facts(dict(world_model.get("agent_profiles", {})), "agent_profiles")
                + _legacy_world_model_items_to_facts(list(world_model.get("social_rules", [])), "social_rules")
            ),
            inferred_memories=[
                _durable_memory_from_dict(item, InferredMemory)
                for item in list(world_model.get("inferred_memories", []))
            ],
            relationship_history=[
                _relationship_memory_from_dict(item)
                for item in list(world_model.get("relationship_history", []))
            ],
            pending_confirmations=[
                _durable_memory_from_dict(item)
                for item in list(world_model.get("pending_confirmations", []))
            ],
            memory_conflicts=[
                _durable_memory_from_dict(item)
                for item in list(world_model.get("memory_conflicts", []))
            ],
        ),
        personality=PersonalityState(
            core_personality=_core_personality_from_dict(
                dict(personality.get("core_personality", {}))
                if personality.get("core_personality")
                else {
                    "baseline_description": personality.get("baseline_description", ""),
                    "behavioral_rules": list(personality.get("behavioral_rules", [])),
                    "traits_internal": dict(personality.get("traits_internal", {})),
                    "version": personality.get("version", 1),
                }
            ),
            relationship_style=_relationship_style_from_dict(
                dict(personality.get("relationship_style", {}))
            ),
            session_adaptation=_session_adaptation_from_dict(
                dict(personality.get("session_adaptation", {}))
                if personality.get("session_adaptation")
                else {
                    "current_items": list(personality.get("session_adaptations", [])),
                    "max_items": 5,
                }
            ),
            version=int(personality.get("version", 1)),
            snapshot_version=int(personality.get("snapshot_version", 0)),
            last_snapshot_at=str(personality.get("last_snapshot_at", "")),
            rollback_count=int(personality.get("rollback_count", 0)),
            snapshot_refs=list(personality.get("snapshot_refs", [])),
        ),
        task_experience=TaskExperience(
            lesson_digest=[
                _memory_entry_from_dict(item)
                for item in list(task_experience.get("lesson_digest", []))
            ],
            domain_tips={
                key: [_memory_entry_from_dict(item) for item in list(items)]
                for key, items in dict(task_experience.get("domain_tips", {})).items()
            },
            agent_habits={
                key: [_memory_entry_from_dict(item) for item in list(items)]
                for key, items in dict(task_experience.get("agent_habits", {})).items()
            },
        ),
    )


class CoreMemoryStore:
    """Persist and retrieve per-user core memory snapshots from PostgreSQL."""

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres.dsn
        self._pool: asyncpg.Pool | None = None

    async def _get_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(dsn=self.dsn)
        return self._pool

    async def load_latest(self, user_id: str) -> CoreMemory:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT snapshot_json
                FROM core_memory_snapshots
                WHERE user_id = $1
                ORDER BY version DESC, created_at DESC
                LIMIT 1
                """,
                user_id,
            )
        if row is None:
            return CoreMemory()
        snapshot = row["snapshot_json"]
        if isinstance(snapshot, str):
            snapshot = json.loads(snapshot)
        return _core_memory_from_dict(dict(snapshot))

    async def save_snapshot(self, user_id: str, core_memory: CoreMemory, version: int) -> None:
        pool = await self._get_pool()
        payload = asdict(core_memory)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO core_memory_snapshots (user_id, version, snapshot_json)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (user_id, version)
                DO UPDATE SET snapshot_json = EXCLUDED.snapshot_json
                """,
                user_id,
                version,
                json.dumps(payload),
            )

    async def list_snapshots(self, user_id: str) -> list[dict[str, Any]]:
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, version, created_at
                FROM core_memory_snapshots
                WHERE user_id = $1
                ORDER BY version DESC, created_at DESC
                """,
                user_id,
            )
        return [dict(row) for row in rows]
