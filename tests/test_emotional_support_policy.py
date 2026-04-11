from __future__ import annotations

import pytest

from app.evolution.event_bus import Event
from app.evolution.signal_extractor import SignalExtractor
from app.memory import CoreMemory, FactualMemory
from app.soul import SoulEngine

from tests.conftest import (
    DummyCoreMemoryCache,
    DummyModelRegistry,
    DummySessionContextStore,
    DummyToolCatalog,
    DummyVectorRetriever,
)


class RecordingPersonalityEvolver:
    def __init__(self) -> None:
        self.signals: list[object] = []

    async def fast_adapt(self, signal: object) -> None:
        self.signals.append(signal)


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


def build_engine(core_memory: CoreMemory | None = None) -> SoulEngine:
    return SoulEngine(
        model_registry=DummyModelRegistry(),
        core_memory_cache=DummyCoreMemoryCache(core_memory=core_memory or CoreMemory()),
        session_context_store=DummySessionContextStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )


def test_emotional_interpretation_detects_overwhelm_and_duration() -> None:
    engine = build_engine()

    interpretation = engine._interpret_emotion("I've been overwhelmed for weeks and I'm really struggling", CoreMemory())

    assert interpretation.emotion_class == "overwhelm"
    assert interpretation.intensity == "high"
    assert interpretation.duration_hint == "ongoing"


def test_emotional_interpretation_defaults_to_neutral_without_overclaiming() -> None:
    interpretation = SoulEngine._interpret_emotion("Can you review this file?", CoreMemory())

    assert interpretation.emotion_class == "neutral"
    assert interpretation.emotional_risk == "low"


@pytest.mark.asyncio
async def test_signal_extractor_emits_support_preference_lesson_for_explicit_listening_request() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(personality_evolver=personality_evolver, event_bus=event_bus)

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-1",
                "text": "Please just listen first and don't give advice yet",
                "reply": "Understood",
            },
        )
    )

    assert event_bus.events
    lesson = event_bus.events[0].payload["lesson"]
    assert lesson["domain"] == "support_preference"
    assert lesson["details"]["support_preference"] == "listening"
    assert lesson["details"]["explicit_user_statement"] is True


@pytest.mark.asyncio
async def test_signal_extractor_emits_proactivity_preference_lesson_for_explicit_suppression() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(personality_evolver=personality_evolver, event_bus=event_bus)

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-1",
                "text": "Please don't follow up on this later and don't remind me",
                "reply": "Understood",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    proactivity = next(item for item in lessons if item["domain"] == "proactivity_preference")
    assert proactivity["details"]["proactivity_preference"] == "suppress"
    assert proactivity["details"]["explicit_user_statement"] is True


def test_support_policy_uses_stored_problem_solving_preference_when_current_turn_is_ambiguous() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers actionable problem-solving support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:problem_solving",
        )
    )
    interpretation = SoulEngine._interpret_emotion("I'm stressed about this bug", core_memory)

    policy = SoulEngine._build_support_policy("I'm stressed about this bug", core_memory, interpretation)

    assert policy.stored_preference == "problem_solving"
    assert policy.support_mode == "problem_solving"
