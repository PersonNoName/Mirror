"""Core memory data contracts and cache support."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


CORE_MEMORY_INVALIDATION_CHANNEL = "core_memory:invalidate"


@dataclass(slots=True)
class MemoryEntry:
    """Generic memory entry with pinning support."""

    content: Any
    is_pinned: bool = False


@dataclass(slots=True)
class CapabilityEntry:
    """Capability statement tracked in self-cognition."""

    description: str
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BehavioralRule:
    """Natural-language rule that can be injected into prompts."""

    rule: str
    rationale: str = ""
    priority: int = 1
    source: str = "system"
    confidence: float = 0.0
    is_pinned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SelfCognition:
    """Persistent self-model maintained per user."""

    capability_map: dict[str, CapabilityEntry] = field(default_factory=dict)
    known_limits: list[MemoryEntry] = field(default_factory=list)
    mission_clarity: list[MemoryEntry] = field(default_factory=list)
    blindspots: list[MemoryEntry] = field(default_factory=list)
    version: int = 1


@dataclass(slots=True)
class WorldModel:
    """Readonly worldview snapshot synthesized from durable stores."""

    env_constraints: list[MemoryEntry] = field(default_factory=list)
    user_model: dict[str, MemoryEntry] = field(default_factory=dict)
    agent_profiles: dict[str, MemoryEntry] = field(default_factory=dict)
    social_rules: list[MemoryEntry] = field(default_factory=list)


@dataclass(slots=True)
class PersonalityState:
    """Personality baseline and adaptive rule state."""

    baseline_description: str = ""
    behavioral_rules: list[BehavioralRule] = field(default_factory=list)
    traits_internal: dict[str, float] = field(default_factory=dict)
    session_adaptations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TaskExperience:
    """Compressed task learnings retained in core memory."""

    lesson_digest: list[MemoryEntry] = field(default_factory=list)
    domain_tips: dict[str, list[MemoryEntry]] = field(default_factory=dict)
    agent_habits: dict[str, list[MemoryEntry]] = field(default_factory=dict)


@dataclass(slots=True)
class CoreMemory:
    """Per-user core memory composed of four durable prompt blocks."""

    self_cognition: SelfCognition = field(default_factory=SelfCognition)
    world_model: WorldModel = field(default_factory=WorldModel)
    personality: PersonalityState = field(default_factory=PersonalityState)
    task_experience: TaskExperience = field(default_factory=TaskExperience)


class CoreMemoryCache:
    """Per-user in-process core memory cache with optional Redis invalidation."""

    def __init__(self, store: Any, redis_client: Any | None = None) -> None:
        self.store = store
        self.redis_client = redis_client
        self._cache: dict[str, CoreMemory] = {}
        self._versions: dict[str, int | None] = {}
        self._active_sessions: dict[str, set[str]] = defaultdict(set)

    async def get(self, user_id: str) -> CoreMemory:
        """Return cached core memory, lazily loading from the store."""

        if user_id not in self._cache:
            try:
                self._cache[user_id] = await self.store.load_latest(user_id)
            except Exception:
                self._cache[user_id] = CoreMemory()
        return self._cache[user_id]

    async def set(
        self,
        user_id: str,
        core_memory: CoreMemory,
        version: int | None = None,
    ) -> None:
        """Update the in-process cache and broadcast invalidation if configured."""

        self._cache[user_id] = core_memory
        self._versions[user_id] = version
        await self._publish_invalidation(user_id)

    async def invalidate(self, user_id: str) -> CoreMemory:
        """Reload a user's core memory from the store."""

        try:
            self._cache[user_id] = await self.store.load_latest(user_id)
        except Exception:
            self._cache[user_id] = CoreMemory()
        return self._cache[user_id]

    def mark_session_active(self, user_id: str, session_id: str) -> None:
        """Track an active session for future invalidation fan-out."""

        self._active_sessions[user_id].add(session_id)

    def mark_session_inactive(self, user_id: str, session_id: str) -> None:
        """Remove a session from the active-session tracking set."""

        active = self._active_sessions.get(user_id)
        if not active:
            return
        active.discard(session_id)
        if not active:
            self._active_sessions.pop(user_id, None)

    async def _publish_invalidation(self, user_id: str) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.publish(CORE_MEMORY_INVALIDATION_CHANNEL, user_id)


def default_core_memory_factory() -> Callable[[], CoreMemory]:
    """Return a factory for empty per-user core memory."""

    return CoreMemory
