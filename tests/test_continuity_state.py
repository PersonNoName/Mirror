from __future__ import annotations

from types import SimpleNamespace

import pytest
from dataclasses import asdict

from app.evolution.cognition_updater import CognitionUpdater
from app.evolution.event_bus import Event
from app.evolution.reflector import MetaCognitionReflector
from app.evolution.signal_extractor import SignalExtractor
from app.tasks.models import Lesson


class _DummyPersonalityEvolver:
    async def fast_adapt(self, signal):  # noqa: ANN001
        return None


class _RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


class _RecordingScheduler:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, object, str | None]] = []

    async def write(self, user_id: str, block: str, content: object, event_id: str | None = None):
        self.writes.append((user_id, block, content, event_id))
        return None


class _StaticCache:
    def __init__(self, core_memory):
        self.core_memory = core_memory

    async def get(self, user_id: str):  # noqa: ANN001
        return self.core_memory


@pytest.mark.asyncio
async def test_signal_extractor_emits_emotional_carryover_lesson() -> None:
    event_bus = _RecordingEventBus()
    extractor = SignalExtractor(
        personality_evolver=_DummyPersonalityEvolver(),
        event_bus=event_bus,
    )
    event = Event(
        type="dialogue_ended",
        payload={
            "user_id": "user-1",
            "session_id": "session-2",
            "text": "我最近工作压力很大，真的有点撑不住了",
            "reply": "我在，慢慢来。",
        },
    )

    await extractor.handle_dialogue_ended(event)

    lessons = [item.payload["lesson"] for item in event_bus.events]
    emotional = [item for item in lessons if item["domain"] == "emotional_continuity"]
    assert emotional
    assert emotional[0]["category"] == "emotional_carryover"
    assert emotional[0]["details"]["emotion_class"] == "overwhelm"


@pytest.mark.asyncio
async def test_cognition_updater_persists_user_emotional_state() -> None:
    from app.memory import CoreMemory

    scheduler = _RecordingScheduler()
    updater = CognitionUpdater(
        core_memory_cache=_StaticCache(CoreMemory()),
        core_memory_scheduler=scheduler,
        graph_store=None,
    )
    lesson = Lesson(
        id="lesson-1",
        user_id="user-1",
        domain="emotional_continuity",
        category="emotional_carryover",
        summary="User shows recent anxiety carryover around work.",
        details={
            "emotion_class": "anxiety",
            "intensity": "medium",
            "emotional_risk": "low",
            "support_mode": "listening",
            "support_preference": "listening",
            "stability": "fragile",
            "unresolved_topics": ["work"],
        },
        confidence=0.9,
    )

    await updater.handle_lesson_generated(Event(type="lesson_generated", payload={"lesson": asdict(lesson)}))

    assert scheduler.writes
    user_id, block, content, _ = scheduler.writes[0]
    assert user_id == "user-1"
    assert block == "user_emotional_state"
    assert getattr(content, "emotion_class") == "anxiety"
    assert getattr(content, "unresolved_topics") == ["work"]


def test_reflector_builds_agent_continuity_lesson_for_failures() -> None:
    lesson = MetaCognitionReflector._build_agent_continuity_lesson(
        SimpleNamespace(
            id="task-1",
            assigned_to="code_agent",
            metadata={"user_id": "user-1", "domain": "python"},
            error_trace="tool failed",
        ),
        outcome="failed",
    )

    assert lesson is not None
    assert lesson.domain == "agent_continuity"
    assert lesson.category == "agent_state_shift"
    assert lesson.details["active_signal"] == "task_failure"
