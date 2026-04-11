from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.api.hitl import router as hitl_router
from app.api.journal import router as journal_router
from app.platform.web import WebPlatformAdapter


class RecordingCoreMemoryCache:
    def __init__(self) -> None:
        self.active_sessions: list[tuple[str, str]] = []

    def mark_session_active(self, user_id: str, session_id: str) -> None:
        self.active_sessions.append((user_id, session_id))


class RecordingSessionContextStore:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str, dict[str, Any]]] = []

    async def append_message(self, user_id: str, session_id: str, message: dict[str, Any]) -> None:
        self.messages.append((user_id, session_id, message))


class StaticSoulEngine:
    def __init__(self, action: Any) -> None:
        self.action = action

    async def run(self, inbound: Any) -> Any:
        return self.action


class StaticActionRouter:
    def __init__(self, result: dict[str, Any] | None) -> None:
        self.result = result
        self.calls: list[tuple[Any, Any]] = []

    async def route(self, action: Any, inbound: Any) -> dict[str, Any] | None:
        self.calls.append((action, inbound))
        return self.result


class RecordingBlackboard:
    def __init__(self, task: Any | None = None) -> None:
        self.task = task
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def resume(self, task_id: str, payload: dict[str, Any]) -> Any | None:
        self.calls.append((task_id, payload))
        return self.task


class RecordingTaskSystem:
    def __init__(self) -> None:
        self.hitl_responses: list[tuple[str, str, dict[str, Any]]] = []

    async def register_hitl_response(self, task_id: str, decision: str, payload: dict[str, Any]) -> None:
        self.hitl_responses.append((task_id, decision, payload))


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class StaticEvolutionJournal:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.calls: list[tuple[int, str | None]] = []

    async def list_recent(self, limit: int = 20, user_id: str | None = None) -> list[Any]:
        self.calls.append((limit, user_id))
        return self.items[:limit]


class PreloadedWebPlatformAdapter(WebPlatformAdapter):
    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.events = events or []

    def subscribe(self, session_id: str):  # type: ignore[override]
        queue = super().subscribe(session_id)
        for event in self.events:
            queue.put_nowait(event)
        return queue


def build_test_app(
    *,
    web_platform: Any | None = None,
    soul_engine: Any | None = None,
    action_router: Any | None = None,
    blackboard: Any | None = None,
    task_system: Any | None = None,
    event_bus: Any | None = None,
    evolution_journal: Any | None = None,
    streaming_disabled: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(hitl_router)
    app.include_router(journal_router)
    app.state.web_platform = web_platform or WebPlatformAdapter()
    app.state.core_memory_cache = RecordingCoreMemoryCache()
    app.state.session_context_store = RecordingSessionContextStore()
    app.state.soul_engine = soul_engine or StaticSoulEngine(action={"type": "direct_reply"})
    app.state.action_router = action_router or StaticActionRouter(
        {"reply": "ok", "action": "direct_reply", "session_id": "session-1"}
    )
    app.state.blackboard = blackboard or RecordingBlackboard(task=SimpleNamespace(id="task-1"))
    app.state.task_system = task_system or RecordingTaskSystem()
    app.state.event_bus = event_bus or RecordingEventBus()
    app.state.event_bus_event_factory = lambda event_type, payload: {"type": event_type, "payload": payload}
    app.state.evolution_journal = evolution_journal or StaticEvolutionJournal(items=[])
    app.state.streaming_disabled = streaming_disabled
    return app


def test_chat_returns_structured_response_model() -> None:
    app = build_test_app(
        action_router=StaticActionRouter(
            {
                "reply": "Task dispatched. Waiting for asynchronous execution.",
                "action": "publish_task",
                "task_id": "task-42",
                "session_id": "session-1",
            }
        )
    )
    client = TestClient(app)

    response = client.post("/chat", json={"text": "run task", "session_id": "session-1", "user_id": "user-1"})

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Task dispatched. Waiting for asynchronous execution.",
        "session_id": "session-1",
        "user_id": "user-1",
        "status": "accepted",
        "meta": {"task_id": "task-42"},
    }
    assert app.state.core_memory_cache.active_sessions == [("user-1", "session-1")]
    assert len(app.state.session_context_store.messages) == 2


def test_chat_rejects_empty_text_and_session_id() -> None:
    app = build_test_app()
    client = TestClient(app)

    response = client.post("/chat", json={"text": "   ", "session_id": "", "user_id": "user-1"})

    assert response.status_code == 422


def test_chat_returns_intentional_error_when_action_routing_fails() -> None:
    app = build_test_app(action_router=StaticActionRouter(None))
    client = TestClient(app)

    response = client.post("/chat", json={"text": "hello", "session_id": "session-1", "user_id": "user-1"})

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "action_routing_failed",
            "message": "The action router did not produce a reply.",
            "details": {"session_id": "session-1"},
        }
    }


def test_chat_stream_returns_structured_error_when_streaming_disabled() -> None:
    app = build_test_app(streaming_disabled=True)
    client = TestClient(app)

    response = client.get("/chat/stream", params={"session_id": "session-1"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "streaming_unavailable",
            "message": "Streaming is currently unavailable for this runtime.",
            "details": {"session_id": "session-1"},
        }
    }


def test_chat_stream_emits_expected_sse_event_sequence() -> None:
    app = build_test_app(
        web_platform=PreloadedWebPlatformAdapter(
            events=[
                {"event": "delta", "data": {"delta": "hello"}},
                {"event": "message", "data": {"type": "text", "content": "hello world", "metadata": {}}},
                {"event": "done", "data": {"status": "done"}},
            ]
        )
    )
    client = TestClient(app)

    with client.stream("GET", "/chat/stream", params={"session_id": "session-1"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: delta" in body
    assert '"delta": "hello"' in body
    assert "event: message" in body
    assert '"content": "hello world"' in body
    assert "event: done" in body
    assert '"status": "done"' in body


def test_hitl_respond_returns_structured_response() -> None:
    app = build_test_app()
    client = TestClient(app)

    response = client.post(
        "/hitl/respond",
        json={"task_id": "task-1", "decision": "approve", "payload": {"safe": True}},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "task_id": "task-1", "decision": "approve"}
    assert app.state.task_system.hitl_responses == [("task-1", "approve", {"safe": True})]
    assert app.state.event_bus.events == [
        {
            "type": "hitl_feedback",
            "payload": {"task_id": "task-1", "decision": "approve", "payload": {"safe": True}},
        }
    ]


def test_hitl_respond_returns_structured_404_for_missing_task() -> None:
    app = build_test_app(blackboard=RecordingBlackboard(task=None))
    client = TestClient(app)

    response = client.post("/hitl/respond", json={"task_id": "missing", "decision": "reject", "payload": {}})

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "task_not_found",
            "message": "No HITL task exists for the provided task_id.",
            "details": {"task_id": "missing"},
        }
    }


def test_hitl_respond_rejects_invalid_decision_and_empty_task_id() -> None:
    app = build_test_app()
    client = TestClient(app)

    invalid_decision = client.post("/hitl/respond", json={"task_id": "task-1", "decision": "maybe", "payload": {}})
    empty_task_id = client.post("/hitl/respond", json={"task_id": "  ", "decision": "approve", "payload": {}})

    assert invalid_decision.status_code == 422
    assert empty_task_id.status_code == 422


def test_evolution_journal_returns_typed_envelope() -> None:
    item = SimpleNamespace(
        id="entry-1",
        user_id="user-1",
        event_type="lesson_generated",
        summary="Captured a lesson",
        details={"domain": "python"},
        created_at=datetime(2026, 4, 11, 10, 0, tzinfo=timezone.utc),
    )
    app = build_test_app(evolution_journal=StaticEvolutionJournal(items=[item]))
    client = TestClient(app)

    response = client.get("/evolution/journal", params={"limit": 10, "user_id": "user-1"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": "entry-1",
                "user_id": "user-1",
                "event_type": "lesson_generated",
                "summary": "Captured a lesson",
                "details": {"domain": "python"},
                "created_at": "2026-04-11T10:00:00Z",
            }
        ],
        "count": 1,
    }
