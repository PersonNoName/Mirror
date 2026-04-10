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
    category: str = "general"
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    created_at: datetime = field(default_factory=utc_now)


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

