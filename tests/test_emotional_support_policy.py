from __future__ import annotations

import pytest

from app.evolution.event_bus import Event
from app.evolution.signal_extractor import SignalExtractor
from app.memory import CoreMemory, FactualMemory
from app.soul import SoulEngine

from tests.conftest import (
    DummyChatModel,
    DummyCoreMemoryCache,
    DummyMidTermMemoryStore,
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
        mid_term_memory_store=DummyMidTermMemoryStore(),
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


@pytest.mark.asyncio
async def test_signal_extractor_emits_explicit_preference_lesson_for_chinese_python_like_statement() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(personality_evolver=personality_evolver, event_bus=event_bus)

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-2",
                "text": "\u6211\u5f88\u559c\u6b22python",
                "reply": "\u6536\u5230",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    explicit = next(item for item in lessons if item["domain"] == "explicit_preference")
    assert explicit["summary"] == "User likes Python."
    assert explicit["details"]["preference_relation"] == "likes"
    assert explicit["details"]["preference_object"] == "Python"
    assert explicit["details"]["explicit_user_statement"] is True


@pytest.mark.asyncio
async def test_signal_extractor_routes_quoted_preference_to_review_instead_of_direct_fact() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(personality_evolver=personality_evolver, event_bus=event_bus)

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-3",
                "text": "\u4e0b\u9762\u662f\u6211\u590d\u5236\u7684\u4e00\u6bb5\u8bdd\uff1a\u201c\u6211\u559c\u6b22Python\u201d",
                "reply": "ok",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    explicit = next(item for item in lessons if item["domain"] == "explicit_preference")
    assert explicit["summary"] == "User likes Python."
    assert explicit["details"]["explicit_user_statement"] is False
    assert explicit["details"]["explicit_user_confirmation"] is False
    assert explicit["details"]["requires_review"] is True
    assert explicit["details"]["review_reason"] == "quoted_or_copied_content"


@pytest.mark.asyncio
async def test_signal_extractor_uses_ai_reviewer_to_restore_self_reported_preference_when_context_says_quote_is_own_view() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(
        personality_evolver=personality_evolver,
        event_bus=event_bus,
        model_registry=DummyModelRegistry(
            chat_model=DummyChatModel(
                response='{"classification":"self_reported","confidence":0.88,"reason":"user says the quoted sentence is also their own preference"}'
            )
        ),
    )

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-4",
                "text": '\u6211\u628a\u8fd9\u53e5\u8bdd\u590d\u5236\u7ed9\u4f60\uff0c\u4f46\u8fd9\u4e5f\u662f\u6211\u81ea\u5df1\u7684\u60f3\u6cd5\uff1a"\u6211\u559c\u6b22Python"',
                "reply": "ok",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    explicit = next(item for item in lessons if item["domain"] == "explicit_preference")
    assert explicit["details"]["explicit_user_statement"] is True
    assert explicit["details"]["review_source"] == "llm_reviewer"
    assert explicit["details"]["review_classification"] == "self_reported"
    assert explicit["confidence"] == pytest.approx(0.88)


@pytest.mark.asyncio
async def test_signal_extractor_uses_ai_reviewer_to_keep_ambiguous_copy_as_review() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(
        personality_evolver=personality_evolver,
        event_bus=event_bus,
        model_registry=DummyModelRegistry(
            chat_model=DummyChatModel(
                response='{"classification":"uncertain","confidence":0.41,"reason":"message may be a pasted example"}'
            )
        ),
    )

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-5",
                "text": "\u6211\u590d\u5236\u4e00\u53e5\u8bdd\u7ed9\u4f60\uff1a\u201c\u6211\u559c\u6b22Python\u201d",
                "reply": "ok",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    explicit = next(item for item in lessons if item["domain"] == "explicit_preference")
    assert explicit["details"]["explicit_user_statement"] is False
    assert explicit["details"]["review_reason"] == "ambiguous_preference_evidence"
    assert explicit["details"]["review_source"] == "llm_reviewer"
    assert explicit["confidence"] == pytest.approx(0.41)


@pytest.mark.asyncio
async def test_signal_extractor_treats_summary_request_as_reviewable_preference_evidence_without_ai() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(personality_evolver=personality_evolver, event_bus=event_bus)

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-6",
                "text": "\u5e2e\u6211\u603b\u7ed3\u4e00\u4e0b\u4e0b\u9762\u7684\u8bdd\uff1a\u6211\u559c\u6b22Python",
                "reply": "ok",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    explicit = next(item for item in lessons if item["domain"] == "explicit_preference")
    assert explicit["details"]["explicit_user_statement"] is False
    assert explicit["details"]["requires_review"] is True
    assert explicit["details"]["review_source"] == "rule_fallback"
    assert explicit["details"]["review_reason"] == "quoted_or_copied_content"


@pytest.mark.asyncio
async def test_signal_extractor_extracts_implicit_preference_candidate_for_situational_coffee_statement() -> None:
    personality_evolver = RecordingPersonalityEvolver()
    event_bus = RecordingEventBus()
    extractor = SignalExtractor(
        personality_evolver=personality_evolver,
        event_bus=event_bus,
        model_registry=DummyModelRegistry(
            chat_model=DummyChatModel(
                response='{"classification":"self_reported","preference_strength":"implicit","durability":"situational","relation":"likes","object":"coffee","confidence":0.63,"reason":"the user expresses enjoyment of coffee in a situation"}'
            )
        ),
    )

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={
                "user_id": "user-1",
                "session_id": "session-7",
                "text": "\u665a\u4e0a\u6765\u676f\u5496\u5561\u771f\u60ec\u610f\u554a",
                "reply": "ok",
            },
        )
    )

    lessons = [event.payload["lesson"] for event in event_bus.events]
    implicit = next(item for item in lessons if item["domain"] == "implicit_preference")
    assert implicit["summary"] == "User may like coffee."
    assert implicit["details"]["preference_strength"] == "implicit"
    assert implicit["details"]["preference_durability"] == "situational"
    assert implicit["details"]["speaker_attribution"] == "self_reported"
    assert implicit["details"]["memory_tier"] == "session_hint"
    assert implicit["confidence"] == pytest.approx(0.63)


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
