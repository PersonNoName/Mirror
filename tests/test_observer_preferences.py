from __future__ import annotations

import asyncio
import json
from contextlib import suppress

import pytest

from app.evolution.event_bus import Event, EventType
from app.evolution.observer import ObserverEngine


class DummyGraphStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []

    async def upsert_relation(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)


class DummyVectorRetriever:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []

    async def upsert(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)


class DummyEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


class DummyChatModel:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[list[dict[str, object]]] = []

    async def generate(self, messages: list[dict[str, object]]) -> object:
        self.calls.append(messages)
        return self.response


class DummyModelRegistry:
    def __init__(self, response: object) -> None:
        self.chat_model = DummyChatModel(response)

    def chat(self, profile: str) -> DummyChatModel:
        assert profile == "lite.extraction"
        return self.chat_model


class SequentialChatModel:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, object]]] = []

    async def generate(self, messages: list[dict[str, object]]) -> object:
        self.calls.append(messages)
        return self.responses.pop(0)


class SequentialModelRegistry:
    def __init__(self, responses: list[object]) -> None:
        self.chat_model = SequentialChatModel(responses)

    def chat(self, profile: str) -> SequentialChatModel:
        assert profile == "lite.extraction"
        return self.chat_model


@pytest.mark.asyncio
async def test_observer_emits_preference_lesson_from_extracted_triple() -> None:
    graph_store = DummyGraphStore()
    vector_retriever = DummyVectorRetriever()
    event_bus = DummyEventBus()
    observer = ObserverEngine(
        model_registry=DummyModelRegistry(
            json.dumps(
                [
                    {
                        "subject": "user",
                        "relation": "PREFERS",
                        "object": "python",
                        "confidence": 0.91,
                    }
                ]
            )
        ),
        graph_store=graph_store,
        vector_retriever=vector_retriever,
        event_bus=event_bus,
    )

    await observer.handle_dialogue_ended(
        Event(
            type=EventType.DIALOGUE_ENDED,
            payload={
                "user_id": "user-1",
                "session_id": "session-1",
                "text": "我很喜欢python",
                "reply": "好的",
            },
        )
    )
    await observer._flush("user-1")
    observer._flush_tasks["user-1"].cancel()
    with suppress(asyncio.CancelledError):
        await observer._flush_tasks["user-1"]

    lesson_events = [event for event in event_bus.events if event.type == EventType.LESSON_GENERATED]
    observation_events = [event for event in event_bus.events if event.type == EventType.OBSERVATION_DONE]

    assert graph_store.upserts[0]["object"] == "Python"
    assert vector_retriever.upserts[0]["content"] == "user PREFERS Python"
    assert lesson_events
    lesson = lesson_events[0].payload["lesson"]
    assert lesson["domain"] == "explicit_preference"
    assert lesson["details"]["preference_relation"] == "prefers"
    assert lesson["details"]["preference_object"] == "Python"
    assert observation_events[0].payload["triples"][0]["relation"] == "PREFERS"


@pytest.mark.asyncio
async def test_observer_marks_copied_preference_for_review() -> None:
    graph_store = DummyGraphStore()
    vector_retriever = DummyVectorRetriever()
    event_bus = DummyEventBus()
    observer = ObserverEngine(
        model_registry=DummyModelRegistry(
            json.dumps(
                [
                    {
                        "subject": "user",
                        "relation": "PREFERS",
                        "object": "python",
                        "confidence": 0.91,
                    }
                ]
            )
        ),
        graph_store=graph_store,
        vector_retriever=vector_retriever,
        event_bus=event_bus,
    )

    await observer.handle_dialogue_ended(
        Event(
            type=EventType.DIALOGUE_ENDED,
            payload={
                "user_id": "user-1",
                "session_id": "session-2",
                "text": "\u4e0b\u9762\u662f\u6211\u590d\u5236\u7684\u4e00\u53e5\u8bdd\uff1a\u201c\u6211\u559c\u6b22Python\u201d",
                "reply": "\u660e\u767d",
            },
        )
    )
    await observer._flush("user-1")
    observer._flush_tasks["user-1"].cancel()
    with suppress(asyncio.CancelledError):
        await observer._flush_tasks["user-1"]

    lesson_events = [event for event in event_bus.events if event.type == EventType.LESSON_GENERATED]
    lesson = lesson_events[0].payload["lesson"]
    assert lesson["details"]["explicit_user_statement"] is False
    assert lesson["details"]["requires_review"] is True
    assert lesson["details"]["review_reason"] == "quoted_or_copied_content"


@pytest.mark.asyncio
async def test_observer_uses_ai_reviewer_for_ambiguous_preference_context() -> None:
    graph_store = DummyGraphStore()
    vector_retriever = DummyVectorRetriever()
    event_bus = DummyEventBus()
    observer = ObserverEngine(
        model_registry=SequentialModelRegistry(
            [
                json.dumps(
                    [
                        {
                            "subject": "user",
                            "relation": "PREFERS",
                            "object": "python",
                            "confidence": 0.91,
                        }
                    ]
                ),
                '{"classification":"uncertain","confidence":0.37,"reason":"message looks like quoted evidence"}',
            ]
        ),
        graph_store=graph_store,
        vector_retriever=vector_retriever,
        event_bus=event_bus,
    )

    await observer.handle_dialogue_ended(
        Event(
            type=EventType.DIALOGUE_ENDED,
            payload={
                "user_id": "user-1",
                "session_id": "session-3",
                "text": '\u6211\u5f15\u7528\u4e00\u53e5\u8bdd\uff0c\u4f60\u5e2e\u6211\u770b\u770b\uff1a"\u6211\u559c\u6b22Python"',
                "reply": "\u660e\u767d",
            },
        )
    )
    await observer._flush("user-1")
    observer._flush_tasks["user-1"].cancel()
    with suppress(asyncio.CancelledError):
        await observer._flush_tasks["user-1"]

    lesson_events = [event for event in event_bus.events if event.type == EventType.LESSON_GENERATED]
    lesson = lesson_events[0].payload["lesson"]
    assert lesson["details"]["explicit_user_statement"] is False
    assert lesson["details"]["review_reason"] == "ambiguous_preference_evidence"
    assert lesson["details"]["review_source"] == "llm_reviewer"
    assert lesson["category"] == "observer_explicit_preference_review"
    assert lesson["confidence"] == pytest.approx(0.37)


@pytest.mark.asyncio
async def test_observer_fallback_marks_summary_request_as_review_even_without_reviewer_json() -> None:
    graph_store = DummyGraphStore()
    vector_retriever = DummyVectorRetriever()
    event_bus = DummyEventBus()
    observer = ObserverEngine(
        model_registry=DummyModelRegistry(
            json.dumps(
                [
                    {
                        "subject": "user",
                        "relation": "PREFERS",
                        "object": "python",
                        "confidence": 0.91,
                    }
                ]
            )
        ),
        graph_store=graph_store,
        vector_retriever=vector_retriever,
        event_bus=event_bus,
    )

    await observer.handle_dialogue_ended(
        Event(
            type=EventType.DIALOGUE_ENDED,
            payload={
                "user_id": "user-1",
                "session_id": "session-4",
                "text": "\u5e2e\u6211\u603b\u7ed3\u4e00\u4e0b\u4e0b\u9762\u7684\u8bdd\uff1a\u6211\u559c\u6b22Python",
                "reply": "\u660e\u767d",
            },
        )
    )
    await observer._flush("user-1")
    observer._flush_tasks["user-1"].cancel()
    with suppress(asyncio.CancelledError):
        await observer._flush_tasks["user-1"]

    lesson_events = [event for event in event_bus.events if event.type == EventType.LESSON_GENERATED]
    lesson = lesson_events[0].payload["lesson"]
    assert lesson["details"]["explicit_user_statement"] is False
    assert lesson["details"]["review_source"] == "rule_fallback"
    assert lesson["details"]["review_reason"] == "quoted_or_copied_content"
    assert lesson["category"] == "observer_explicit_preference_review"
