from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.chat import router as chat_router
from app.api.hitl import router as hitl_router
from app.api.journal import router as journal_router
from app.api.memory import router as memory_router
from app.api.prompts import router as prompts_router
from app.observability import ChatTraceService
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

    async def run(self, inbound: Any, **kwargs: Any) -> Any:
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


class RecordingProactivityService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    async def deliver_follow_up(self, *, user_id: str, ctx: Any, platform_adapter: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((user_id, ctx))
        return {"eligible": False, "reason": "none"}


class StaticEvolutionJournal:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.calls: list[tuple[int, str | None]] = []

    async def list_recent(self, limit: int = 20, user_id: str | None = None) -> list[Any]:
        self.calls.append((limit, user_id))
        return self.items[:limit]


class RecordingMemoryGovernanceService:
    def __init__(self) -> None:
        self.list_calls: list[tuple[str, bool, bool]] = []
        self.get_policy_calls: list[str] = []
        self.block_calls: list[tuple[str, str, bool]] = []
        self.correct_calls: list[dict[str, Any]] = []
        self.delete_calls: list[tuple[str, str, str]] = []
        self.delete_mid_term_calls: list[tuple[str, str, str]] = []
        self.memory_items: list[dict[str, Any]] = []
        self.policy = {
            "blocked_content_classes": [],
            "retention_days": {
                "fact": 0,
                "relationship": 0,
                "inference": 30,
                "pending_confirmation": 7,
                "memory_conflicts": 30,
                "candidate": 7,
            },
            "updated_at": "2026-04-11T10:00:00+00:00",
        }

    async def list_memory(
        self,
        *,
        user_id: str,
        include_candidates: bool = True,
        include_superseded: bool = False,
        include_mid_term: bool = False,
    ):
        self.list_calls.append((user_id, include_candidates, include_superseded))
        return list(self.memory_items)

    async def get_policy(self, user_id: str):
        self.get_policy_calls.append(user_id)
        return SimpleNamespace(**self.policy)

    async def set_blocked(self, *, user_id: str, content_class: str, blocked: bool):
        self.block_calls.append((user_id, content_class, blocked))
        classes = set(self.policy["blocked_content_classes"])
        if blocked:
            classes.add(content_class)
        else:
            classes.discard(content_class)
        self.policy["blocked_content_classes"] = sorted(classes)
        return SimpleNamespace(**self.policy)

    async def correct_memory(self, **kwargs: Any):
        self.correct_calls.append(kwargs)
        if kwargs["memory_key"] == "missing":
            raise KeyError("missing")
        return {
            "memory_key": kwargs["memory_key"] + ":corrected",
            "content": kwargs["corrected_content"],
            "truth_type": kwargs["truth_type"],
            "status": "active",
            "source": "user_correction",
            "confidence": 1.0,
            "confirmed_by_user": True,
            "updated_at": "2026-04-11T10:00:00+00:00",
            "visibility": "durable",
        }

    async def delete_memory(self, *, user_id: str, memory_key: str, reason: str):
        self.delete_calls.append((user_id, memory_key, reason))
        if memory_key == "missing":
            raise KeyError("missing")
        return None

    async def delete_mid_term_memory(self, *, user_id: str, memory_key: str, reason: str):
        self.delete_mid_term_calls.append((user_id, memory_key, reason))
        if memory_key == "missing":
            raise KeyError("missing")
        return None


class PreloadedWebPlatformAdapter(WebPlatformAdapter):
    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.events = events or []

    def subscribe(self, session_id: str):  # type: ignore[override]
        queue = super().subscribe(session_id)
        for event in self.events:
            queue.put_nowait(event)
        return queue


class RecordingVectorRetriever:
    def __init__(self, items: list[dict[str, Any]] | None = None, error: str | None = None) -> None:
        self.items = items or []
        self.error = error
        self.calls: list[tuple[str, str, int]] = []

    async def list_namespace_items(self, *, user_id: str, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        self.calls.append((user_id, namespace, limit))
        return list(self.items)[:limit]

    def last_namespace_list_error(self, *, user_id: str, namespace: str) -> str | None:
        return self.error


def build_test_app(
    *,
    web_platform: Any | None = None,
    soul_engine: Any | None = None,
    action_router: Any | None = None,
    blackboard: Any | None = None,
    task_system: Any | None = None,
    event_bus: Any | None = None,
    proactivity_service: Any | None = None,
    evolution_journal: Any | None = None,
    memory_governance_service: Any | None = None,
    vector_retriever: Any | None = None,
    streaming_disabled: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(hitl_router)
    app.include_router(journal_router)
    app.include_router(memory_router)
    app.include_router(prompts_router)
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
    app.state.proactivity_service = proactivity_service or RecordingProactivityService()
    app.state.event_bus_event_factory = lambda event_type, payload: {"type": event_type, "payload": payload}
    app.state.evolution_journal = evolution_journal or StaticEvolutionJournal(items=[])
    app.state.memory_governance_service = memory_governance_service or RecordingMemoryGovernanceService()
    app.state.mid_term_memory_store = SimpleNamespace(degraded=False, degraded_reason=None, storage_source="postgres")
    app.state.vector_retriever = vector_retriever
    app.state.chat_trace_service = ChatTraceService(emitter=app.state.web_platform.emit_trace)
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
    body = response.json()
    assert body["reply"] == "Task dispatched. Waiting for asynchronous execution."
    assert body["session_id"] == "session-1"
    assert body["user_id"] == "user-1"
    assert body["status"] == "accepted"
    assert body["meta"]["task_id"] == "task-42"
    assert body["meta"]["trace_id"]
    assert body["trace"] is None
    assert body["brain"] is None
    assert app.state.core_memory_cache.active_sessions == [("user-1", "session-1")]
    assert len(app.state.session_context_store.messages) == 2


def test_chat_can_return_trace_when_requested() -> None:
    app = build_test_app()
    client = TestClient(app)

    response = client.post(
        "/chat",
        json={"text": "hello", "session_id": "session-1", "user_id": "user-1", "include_trace": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["trace_id"]
    assert body["trace"]["session_id"] == "session-1"
    assert body["trace"]["status"] == "completed"
    assert len(body["trace"]["steps"]) >= 3
    assert body["brain"] is None


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


def test_chat_stream_registers_user_presence_and_checks_proactive_followup() -> None:
    proactivity = RecordingProactivityService()
    app = build_test_app(
        proactivity_service=proactivity,
        web_platform=PreloadedWebPlatformAdapter(events=[{"event": "done", "data": {"status": "done"}}]),
    )
    client = TestClient(app)

    with client.stream("GET", "/chat/stream", params={"session_id": "session-1", "user_id": "user-1"}) as response:
        _ = "".join(response.iter_text())

    assert response.status_code == 200
    assert proactivity.calls
    assert proactivity.calls[0][0] == "user-1"


def test_chat_trace_returns_latest_trace_for_session() -> None:
    app = build_test_app()
    client = TestClient(app)

    chat_response = client.post(
        "/chat",
        json={"text": "trace me", "session_id": "session-1", "user_id": "user-1"},
    )

    assert chat_response.status_code == 200
    trace_response = client.get("/chat/trace", params={"session_id": "session-1"})

    assert trace_response.status_code == 200
    assert trace_response.json()["session_id"] == "session-1"
    assert trace_response.json()["status"] == "completed"


def test_chat_trace_returns_404_when_missing() -> None:
    app = build_test_app()
    client = TestClient(app)

    response = client.get("/chat/trace", params={"session_id": "missing"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "trace_not_found"


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


def test_memory_routes_return_governed_memory_and_policy() -> None:
    service = RecordingMemoryGovernanceService()
    service.memory_items = [
        {
            "memory_key": "fact:preferences:short",
            "content": "User prefers short answers",
            "truth_type": "fact",
            "status": "active",
            "source": "user",
            "confidence": 1.0,
            "confirmed_by_user": True,
            "updated_at": "2026-04-11T10:00:00+00:00",
            "visibility": "durable",
        },
        {
            "memory_key": "support_preference:listening",
            "content": "User prefers listening-first support",
            "truth_type": "fact",
            "status": "candidate",
            "source": "dialogue_signal",
            "confidence": 0.9,
            "confirmed_by_user": False,
            "updated_at": "2026-04-11T09:00:00+00:00",
            "visibility": "candidate",
        },
    ]
    app = build_test_app(memory_governance_service=service)
    client = TestClient(app)

    memory_response = client.get("/memory", params={"user_id": "user-1"})
    policy_response = client.get("/memory/governance", params={"user_id": "user-1"})

    assert memory_response.status_code == 200
    assert memory_response.json()["count"] == 2
    assert memory_response.json()["items"][1]["visibility"] == "candidate"
    assert policy_response.status_code == 200
    assert policy_response.json()["blocked_content_classes"] == []


def test_memory_routes_support_correct_delete_and_block() -> None:
    service = RecordingMemoryGovernanceService()
    app = build_test_app(memory_governance_service=service)
    client = TestClient(app)

    correct_response = client.post(
        "/memory/correct",
        json={
            "user_id": "user-1",
            "memory_key": "inference:tone:direct",
            "corrected_content": "User prefers careful detailed answers",
            "truth_type": "fact",
        },
    )
    delete_response = client.post(
        "/memory/delete",
        json={"user_id": "user-1", "memory_key": "fact:tone:direct", "reason": "wrong"},
    )
    block_response = client.post(
        "/memory/governance/block",
        json={"user_id": "user-1", "content_class": "support_preference", "blocked": True},
    )

    assert correct_response.status_code == 200
    assert correct_response.json()["item"]["source"] == "user_correction"
    assert delete_response.status_code == 200
    assert delete_response.json() == {"status": "ok", "memory_key": "fact:tone:direct"}
    assert block_response.status_code == 200
    assert "support_preference" in block_response.json()["policy"]["blocked_content_classes"]


def test_memory_routes_support_mid_term_listing_and_delete() -> None:
    service = RecordingMemoryGovernanceService()
    service.memory_items = [
        {
            "memory_key": "mid_term:project:mirror-memory",
            "content": "User is working on the mirror memory rollout.",
            "truth_type": "mid_term",
            "status": "active",
            "source": "dialogue_mid_term",
            "confidence": 0.7,
            "confirmed_by_user": False,
            "updated_at": "2026-04-11T10:00:00+00:00",
            "visibility": "mid_term",
        }
    ]
    app = build_test_app(memory_governance_service=service)
    client = TestClient(app)

    list_response = client.get("/memory/mid-term", params={"user_id": "user-1"})
    delete_response = client.post(
        "/memory/mid-term/delete",
        json={"user_id": "user-1", "memory_key": "mid_term:project:mirror-memory", "reason": "clear"},
    )

    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["degraded"] is False
    assert list_response.json()["source"] == "postgres"
    assert list_response.json()["items"][0]["visibility"] == "mid_term"
    assert delete_response.status_code == 200
    assert service.delete_mid_term_calls == [("user-1", "mid_term:project:mirror-memory", "clear")]


def test_memory_routes_expose_mid_term_degraded_state() -> None:
    service = RecordingMemoryGovernanceService()
    app = build_test_app(memory_governance_service=service)
    app.state.mid_term_memory_store = SimpleNamespace(
        degraded=True,
        degraded_reason="mid_term_memory_schema_missing",
        storage_source="memory_fallback",
    )
    client = TestClient(app)

    response = client.get("/memory/mid-term", params={"user_id": "user-1"})

    assert response.status_code == 200
    assert response.json()["degraded"] is True
    assert response.json()["source"] == "memory_fallback"


def test_memory_routes_support_conversation_episode_listing() -> None:
    retriever = RecordingVectorRetriever(
        items=[
            {
                "id": "episode-1",
                "content": "Previous conversation on 2026-04-12. User said: \"We discussed memory.\"",
                "namespace": "conversation_episode",
                "status": "active",
                "truth_type": "fact",
                "confirmed_by_user": False,
                "created_at": "2026-04-12T00:00:00+00:00",
                "metadata": {"session_id": "session-1", "event_id": "evt-1"},
            }
        ]
    )
    app = build_test_app(vector_retriever=retriever)
    client = TestClient(app)

    response = client.get("/memory/conversation-episodes", params={"user_id": "user-1", "limit": 10})

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["degraded"] is False
    assert response.json()["source"] == "qdrant"
    assert response.json()["error"] is None
    assert response.json()["items"][0]["namespace"] == "conversation_episode"
    assert retriever.calls == [("user-1", "conversation_episode", 10)]


def test_memory_routes_expose_conversation_episode_degraded_state() -> None:
    retriever = RecordingVectorRetriever(items=[], error="qdrant_request_failed")
    app = build_test_app(vector_retriever=retriever)
    client = TestClient(app)

    response = client.get("/memory/conversation-episodes", params={"user_id": "user-1", "limit": 10})

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert response.json()["degraded"] is True
    assert response.json()["source"] == "qdrant"
    assert response.json()["error"] == "qdrant_request_failed"


def test_memory_routes_return_404_for_missing_memory_key() -> None:
    service = RecordingMemoryGovernanceService()
    app = build_test_app(memory_governance_service=service)
    client = TestClient(app)

    correct_response = client.post(
        "/memory/correct",
        json={
            "user_id": "user-1",
            "memory_key": "missing",
            "corrected_content": "x",
            "truth_type": "fact",
        },
    )
    delete_response = client.post(
        "/memory/delete",
        json={"user_id": "user-1", "memory_key": "missing", "reason": "wrong"},
    )

    assert correct_response.status_code == 404
    assert delete_response.status_code == 404


def test_prompt_routes_return_core_templates() -> None:
    app = build_test_app()
    client = TestClient(app)

    list_response = client.get("/prompts")
    item_response = client.get("/prompts/soul_core_system")

    assert list_response.status_code == 200
    assert list_response.json()["count"] >= 2
    assert any(item["key"] == "soul_core_system" for item in list_response.json()["items"])
    assert item_response.status_code == 200
    assert item_response.json()["key"] == "soul_core_system"
    assert "## Self Cognition" in item_response.json()["content"]


def test_prompt_routes_return_404_for_missing_template() -> None:
    app = build_test_app()
    client = TestClient(app)

    response = client.get("/prompts/missing_key")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "prompt_not_found",
            "message": "No prompt template exists for the provided key.",
            "details": {"key": "missing_key"},
        }
    }
