"""Event bus contracts and shared evolution data models."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


class EventType:
    """Canonical event names used by the async evolution pipeline."""

    DIALOGUE_ENDED = "dialogue_ended"
    OBSERVATION_DONE = "observation_done"
    LESSON_GENERATED = "lesson_generated"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_WAITING_HITL = "task_waiting_hitl"
    HITL_FEEDBACK = "hitl_feedback"
    EVOLUTION_DONE = "evolution_done"

    ALL = frozenset(
        {
            DIALOGUE_ENDED,
            OBSERVATION_DONE,
            LESSON_GENERATED,
            TASK_COMPLETED,
            TASK_FAILED,
            TASK_WAITING_HITL,
            HITL_FEEDBACK,
            EVOLUTION_DONE,
        }
    )


@dataclass(slots=True)
class Event:
    """Transport-ready event payload for the async event bus."""

    type: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    priority: int = 1
    stream_name: str = "events:main"
    delivery_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InteractionSignal:
    """Structured user or runtime signal extracted from interactions."""

    signal_type: str
    user_id: str
    session_id: str
    content: str
    confidence: float = 0.0
    source_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvolutionEntry:
    """Visible growth-log entry produced by the evolution pipeline."""

    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    event_type: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


class EventBus(ABC):
    """Minimal event bus interface for future implementations."""

    @abstractmethod
    async def emit(self, event: Event) -> None:
        """Publish an event to the underlying transport."""

    @abstractmethod
    async def subscribe(self, event_type: str, handler: Any) -> None:
        """Register a handler for a canonical event type."""

