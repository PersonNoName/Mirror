"""Task-layer shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


TaskStatus = Literal[
    "pending",
    "running",
    "waiting_hitl",
    "done",
    "failed",
    "interrupted",
    "cancelled",
]

MemoryConfirmationDecision = Literal["approve", "reject", "defer"]
EvolutionCandidateDecision = Literal["approve", "reject", "defer"]


@dataclass(slots=True)
class TaskResult:
    """Normalized result emitted by a sub-agent task execution."""

    task_id: str
    status: TaskStatus
    output: dict[str, Any] | None = None
    lessons: list[str] = field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class Lesson:
    """Structured lesson produced by reflection or task analysis."""

    id: str = field(default_factory=lambda: str(uuid4()))
    source_task_id: str | None = None
    user_id: str = ""
    domain: str = "general"
    outcome: str = ""
    category: str = "general"
    summary: str = ""
    root_cause: str = ""
    lesson_text: str = ""
    is_agent_capability_issue: bool = False
    subject: str | None = None
    relation: str | None = None
    object: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class MemoryConfirmationRequest:
    """Payload for confirming or rejecting a memory promotion."""

    memory_key: str
    candidate_content: str
    truth_type: Literal["fact", "inference", "relationship"]
    source: str
    reason: str
    options: list[MemoryConfirmationDecision] = field(default_factory=lambda: ["approve", "reject", "defer"])
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvolutionCandidateRequest:
    """Payload for approving or rejecting a high-risk evolution candidate."""

    candidate_id: str
    affected_area: Literal["self_cognition", "world_model", "personality", "relationship_style"]
    risk_level: Literal["low", "medium", "high"]
    evidence_summary: str
    proposed_change: dict[str, Any]
    reason: str
    options: list[EvolutionCandidateDecision] = field(default_factory=lambda: ["approve", "reject", "defer"])
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Task:
    """Task entity shared across routing, execution, and reflection layers."""

    id: str = field(default_factory=lambda: str(uuid4()))
    parent_task_id: str | None = None
    children_task_ids: list[str] = field(default_factory=list)
    created_by: str = "main_agent"
    assigned_to: str = ""
    intent: str = ""
    prompt_snapshot: str = ""
    status: TaskStatus = "pending"
    priority: int = 1
    depends_on: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error_trace: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    last_heartbeat_at: datetime = field(default_factory=utc_now)
    heartbeat_timeout: int = 30
    dispatch_stream: str = "tasks:dispatch"
    consumer_group: str = "main-agent"
    delivery_token: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
