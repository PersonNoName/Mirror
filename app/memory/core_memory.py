"""Core memory data contracts and cache support."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


CORE_MEMORY_INVALIDATION_CHANNEL = "core_memory:invalidate"

TruthType = Literal["fact", "inference", "relationship"]
TimeHorizon = Literal["short_term", "medium_term", "long_term"]
MemoryStatus = Literal["active", "pending_confirmation", "conflicted", "superseded"]
Sensitivity = Literal["normal", "sensitive"]
GovernanceContentClass = Literal["fact", "inference", "relationship", "support_preference"]
RelationshipStage = Literal[
    "unfamiliar",
    "trust_building",
    "stable_companion",
    "vulnerable_support",
    "repair_and_recovery",
]


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class MemoryEntry:
    """Generic memory entry with pinning support."""

    content: Any
    is_pinned: bool = False


@dataclass(slots=True)
class DurableMemory:
    """Base durable memory item with truth and lifecycle metadata."""

    content: str
    source: str
    confidence: float = 0.0
    updated_at: str = field(default_factory=utc_now_iso)
    confirmed_by_user: bool = False
    is_pinned: bool = False
    truth_type: TruthType = "fact"
    time_horizon: TimeHorizon = "long_term"
    status: MemoryStatus = "active"
    sensitivity: Sensitivity = "normal"
    memory_key: str = ""
    conflict_with: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FactualMemory(DurableMemory):
    """User-confirmed or explicit factual memory."""

    truth_type: TruthType = "fact"


@dataclass(slots=True)
class InferredMemory(DurableMemory):
    """System-inferred memory that must remain separate from facts."""

    truth_type: TruthType = "inference"


@dataclass(slots=True)
class RelationshipMemory(DurableMemory):
    """Relationship-oriented memory with explicit graph semantics."""

    subject: str = ""
    relation: str = ""
    object: str = ""
    truth_type: TruthType = "relationship"


@dataclass(slots=True)
class RelationshipStageState:
    """Current relationship-stage snapshot used to modulate foreground behavior."""

    stage: RelationshipStage = "unfamiliar"
    confidence: float = 0.0
    updated_at: str = field(default_factory=utc_now_iso)
    entered_at: str = field(default_factory=utc_now_iso)
    supports_vulnerability: bool = False
    repair_needed: bool = False
    recent_transition_reason: str = ""
    recent_shared_events: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MemoryGovernancePolicy:
    """Per-user governance policy for user-visible world-model memory."""

    blocked_content_classes: list[GovernanceContentClass] = field(default_factory=list)
    retention_days: dict[str, int] = field(
        default_factory=lambda: {
            "fact": 0,
            "relationship": 0,
            "inference": 30,
            "pending_confirmation": 7,
            "memory_conflicts": 30,
            "candidate": 7,
        }
    )
    updated_at: str = field(default_factory=utc_now_iso)


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
class CorePersonality:
    """Stable long-term identity state."""

    baseline_description: str = ""
    behavioral_rules: list[BehavioralRule] = field(default_factory=list)
    traits_internal: dict[str, float] = field(
        default_factory=lambda: {
            "directness": 0.7,
            "supportiveness": 0.6,
            "conciseness": 0.7,
        }
    )
    version: int = 1
    updated_at: str = field(default_factory=utc_now_iso)
    stable_fields: list[str] = field(
        default_factory=lambda: [
            "baseline_description",
            "behavioral_rules",
            "traits_internal",
        ]
    )


@dataclass(slots=True)
class RelationshipStyle:
    """Long-term relational interaction style."""

    warmth: float = 0.5
    boundary_strength: float = 0.8
    supportiveness: float = 0.6
    humor: float = 0.3
    preferred_closeness: str = "steady"
    updated_at: str = field(default_factory=utc_now_iso)


@dataclass(slots=True)
class SessionAdaptation:
    """Short-term per-session adaptation state."""

    current_items: list[str] = field(default_factory=list)
    session_id: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    expires_at: str = field(default_factory=utc_now_iso)
    max_items: int = 5


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
    """Prompt-facing worldview snapshot partitioned by truth and status."""

    confirmed_facts: list[FactualMemory] = field(default_factory=list)
    inferred_memories: list[InferredMemory] = field(default_factory=list)
    relationship_history: list[RelationshipMemory] = field(default_factory=list)
    relationship_stage: RelationshipStageState = field(default_factory=RelationshipStageState)
    memory_governance: MemoryGovernancePolicy = field(default_factory=MemoryGovernancePolicy)
    pending_confirmations: list[DurableMemory] = field(default_factory=list)
    memory_conflicts: list[DurableMemory] = field(default_factory=list)


@dataclass(slots=True)
class PersonalityState:
    """Three-layer personality state with snapshot metadata."""

    core_personality: CorePersonality = field(default_factory=CorePersonality)
    relationship_style: RelationshipStyle = field(default_factory=RelationshipStyle)
    session_adaptation: SessionAdaptation = field(default_factory=SessionAdaptation)
    version: int = 1
    snapshot_version: int = 0
    last_snapshot_at: str = ""
    rollback_count: int = 0
    snapshot_refs: list[dict[str, Any]] = field(default_factory=list)


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
