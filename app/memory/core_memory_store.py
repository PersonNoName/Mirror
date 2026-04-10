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
    CoreMemory,
    MemoryEntry,
    PersonalityState,
    SelfCognition,
    TaskExperience,
    WorldModel,
)


def _memory_entry_from_dict(data: dict[str, Any]) -> MemoryEntry:
    return MemoryEntry(
        content=data.get("content"),
        is_pinned=bool(data.get("is_pinned", False)),
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
            env_constraints=[
                _memory_entry_from_dict(item)
                for item in list(world_model.get("env_constraints", []))
            ],
            user_model={
                key: _memory_entry_from_dict(value)
                for key, value in dict(world_model.get("user_model", {})).items()
            },
            agent_profiles={
                key: _memory_entry_from_dict(value)
                for key, value in dict(world_model.get("agent_profiles", {})).items()
            },
            social_rules=[
                _memory_entry_from_dict(item)
                for item in list(world_model.get("social_rules", []))
            ],
        ),
        personality=PersonalityState(
            baseline_description=personality.get("baseline_description", ""),
            behavioral_rules=[
                _behavioral_rule_from_dict(item)
                for item in list(personality.get("behavioral_rules", []))
            ],
            traits_internal={
                key: float(value)
                for key, value in dict(personality.get("traits_internal", {})).items()
            },
            session_adaptations=list(personality.get("session_adaptations", [])),
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
