from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.base import SubAgent
from app.agents.registry import AgentRegistry
from app.api.chat import router as chat_router
from app.api.hitl import router as hitl_router
from app.api.journal import router as journal_router
from app.evolution.event_bus import Event, EventType
from app.infra.outbox import OutboxEvent
from app.memory import CoreMemory
from app.platform.web import WebPlatformAdapter
from app.soul import ActionRouter, SoulEngine
from app.tasks import Blackboard, TaskResult, TaskStore, TaskSystem, TaskWorker
from app.tools import ToolRegistry

from tests.conftest import DummyChatModel, DummyModelRegistry


class IntegrationCoreMemoryCache:
    def __init__(self, core_memory: CoreMemory | None = None) -> None:
        self.core_memory = core_memory or CoreMemory()
        self.active_sessions: list[tuple[str, str]] = []

    async def get(self, user_id: str) -> CoreMemory:
        return self.core_memory

    def mark_session_active(self, user_id: str, session_id: str) -> None:
        self.active_sessions.append((user_id, session_id))


class IntegrationSessionContextStore:
    def __init__(self) -> None:
        self._messages: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._adaptations: dict[tuple[str, str], list[str]] = {}

    async def append_message(self, user_id: str, session_id: str, message: dict[str, Any]) -> None:
        self._messages.setdefault((user_id, session_id), []).append(dict(message))

    async def get_recent_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        return list(self._messages.get((user_id, session_id), []))

    async def get_adaptations(self, user_id: str, session_id: str) -> list[str]:
        return list(self._adaptations.get((user_id, session_id), []))


class IntegrationOutboxStore:
    def __init__(self) -> None:
        self.events: list[OutboxEvent] = []

    @staticmethod
    def from_payload(topic: str, payload: dict[str, Any]) -> OutboxEvent:
        return OutboxEvent(topic=topic, payload=payload)

    async def enqueue(self, event: OutboxEvent) -> OutboxEvent:
        self.events.append(event)
        return event


class IntegrationEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


class FakeRedisClient:
    def __init__(self) -> None:
        self.acks: list[tuple[str, str, str]] = []

    async def xack(self, stream_name: str, group_name: str, message_id: str) -> None:
        self.acks.append((stream_name, group_name, message_id))


class DeterministicAgent(SubAgent):
    def __init__(self, *, name: str, capability: float, result: TaskResult | None = None) -> None:
        self.name = name
        self.domain = "integration"
        self.capability = capability
        self.result = result

    async def estimate_capability(self, task: Any) -> float:
        return self.capability

    async def execute(self, task: Any) -> TaskResult:
        if self.result is not None:
            return self.result
        return TaskResult(
            task_id=task.id,
            status="done",
            output={"summary": f"Agent {self.name} completed: {task.intent}", "task_id": task.id},
        )


class WaitableWebPlatformAdapter(WebPlatformAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.subscribe_event = threading.Event()

    def subscribe(self, session_id: str):  # type: ignore[override]
        queue = super().subscribe(session_id)
        self.subscribe_event.set()
        return queue


def build_runtime_app(
    *,
    chat_response: str,
    agent_capability: float = 0.0,
    agent_result: TaskResult | None = None,
    streaming_disabled: bool = False,
    vector_retriever: Any | None = None,
    session_context_store: Any | None = None,
) -> tuple[FastAPI, dict[str, Any]]:
    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(hitl_router)
    app.include_router(journal_router)

    core_memory_cache = IntegrationCoreMemoryCache()
    session_store = session_context_store or IntegrationSessionContextStore()
    web_platform = WaitableWebPlatformAdapter()
    outbox_store = IntegrationOutboxStore()
    event_bus = IntegrationEventBus()
    task_store = TaskStore()
    task_system = TaskSystem(task_store=task_store, outbox_store=outbox_store, redis_client=FakeRedisClient())
    agent_registry = AgentRegistry()
    agent = DeterministicAgent(name="integration_agent", capability=agent_capability, result=agent_result)
    agent_registry.register(agent)
    blackboard = Blackboard(
        task_store=task_store,
        task_system=task_system,
        agent_registry=agent_registry,
        event_bus=event_bus,
    )
    soul_engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=DummyChatModel(response=_chat_payload(chat_response))),
        core_memory_cache=core_memory_cache,
        session_context_store=session_store,
        vector_retriever=vector_retriever,
        tool_registry=ToolRegistry(),
    )
    action_router = ActionRouter(
        platform_adapter=web_platform,
        event_bus=event_bus,
        blackboard=blackboard,
        task_system=task_system,
        tool_registry=ToolRegistry(),
    )
    worker = TaskWorker(
        agent=agent,
        task_store=task_store,
        task_system=task_system,
        blackboard=blackboard,
        platform_adapter=web_platform,
    )

    app.state.web_platform = web_platform
    app.state.core_memory_cache = core_memory_cache
    app.state.session_context_store = session_store
    app.state.soul_engine = soul_engine
    app.state.action_router = action_router
    app.state.blackboard = blackboard
    app.state.task_system = task_system
    app.state.task_store = task_store
    app.state.event_bus = event_bus
    app.state.event_bus_event_factory = lambda event_type, payload: Event(type=event_type, payload=payload)
    app.state.evolution_journal = SimpleNamespace(list_recent=_list_recent_empty)
    app.state.streaming_disabled = streaming_disabled

    runtime = {
        "core_memory_cache": core_memory_cache,
        "session_context_store": session_store,
        "web_platform": web_platform,
        "outbox_store": outbox_store,
        "event_bus": event_bus,
        "task_store": task_store,
        "task_system": task_system,
        "blackboard": blackboard,
        "agent": agent,
        "worker": worker,
    }
    return app, runtime


async def _list_recent_empty(limit: int = 20, user_id: str | None = None) -> list[Any]:
    return []


def _chat_payload(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


def _latest_task_id(runtime: dict[str, Any]) -> str:
    assert runtime["outbox_store"].events
    task_payload = runtime["outbox_store"].events[-1].payload["task"]
    return str(task_payload["id"])


async def _load_task(runtime: dict[str, Any], task_id: str) -> Any:
    task = await runtime["task_store"].get(task_id)
    assert task is not None
    return task


def test_integration_chat_direct_reply_happy_path_with_stream_fanout() -> None:
    app, runtime = build_runtime_app(
        chat_response=(
            "<inner_thoughts>reply directly</inner_thoughts>"
            "<action>direct_reply</action>"
            "<content>Hello from integration.</content>"
        ),
        agent_capability=0.0,
    )

    queue = runtime["web_platform"].subscribe("session-1")

    with TestClient(app) as client:
        response = client.post("/chat", json={"text": "hello", "session_id": "session-1", "user_id": "user-1"})
    events = drain_queue(queue)

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Hello from integration.",
        "session_id": "session-1",
        "user_id": "user-1",
        "status": "completed",
        "meta": None,
    }
    assert runtime["core_memory_cache"].active_sessions == [("user-1", "session-1")]
    assert await_sync(runtime["session_context_store"].get_recent_messages("user-1", "session-1")) == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "Hello from integration."},
    ]
    assert runtime["event_bus"].events[0].type == EventType.DIALOGUE_ENDED
    assert [event["event"] for event in events] == ["delta", "message", "done"]
    assert events[1]["data"]["content"] == "Hello from integration."


def test_integration_chat_publish_task_then_worker_completion() -> None:
    app, runtime = build_runtime_app(
        chat_response=(
            "<inner_thoughts>delegate work</inner_thoughts>"
            "<action>publish_task</action>"
            "<content>compile integration status</content>"
        ),
        agent_capability=0.95,
        agent_result=TaskResult(
            task_id="placeholder",
            status="done",
            output={"summary": "Integration worker completed task.", "files_changed": []},
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={"text": "please run async job", "session_id": "session-1", "user_id": "user-1"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    task_id = _latest_task_id(runtime)
    task = await_sync(_load_task(runtime, task_id))
    assert task.status == "running"

    queue = runtime["web_platform"].subscribe("session-1")
    stream_name = runtime["task_system"].stream_for_agent(runtime["agent"].name, runtime["task_system"].DISPATCH_STREAM)
    message_fields = {"task_id": task_id}
    await_sync(runtime["worker"]._handle_message(stream_name, "1-0", message_fields))

    completed_task = await_sync(_load_task(runtime, task_id))
    assert completed_task.status == "done"
    assert completed_task.result == {"summary": "Integration worker completed task.", "files_changed": []}
    assert runtime["event_bus"].events[-1].type == EventType.TASK_COMPLETED
    events = drain_queue(queue)
    assert any(event["event"] == "message" and event["data"]["content"] == "Integration worker completed task." for event in events)
    assert runtime["task_system"].redis_client.acks == [(stream_name, runtime["worker"].group, "1-0")]


def test_integration_hitl_response_loop() -> None:
    app, runtime = build_runtime_app(
        chat_response=(
            "<inner_thoughts>need approval</inner_thoughts>"
            "<action>publish_task</action>"
            "<content>dangerous integration task</content>"
        ),
        agent_capability=0.1,
    )

    queue = runtime["web_platform"].subscribe("session-1")

    with TestClient(app) as client:
        chat_response = client.post(
            "/chat",
            json={"text": "run risky task", "session_id": "session-1", "user_id": "user-1"},
        )
        task_id = chat_response.json()["meta"]["task_id"]
        hitl_response = client.post(
            "/hitl/respond",
            json={"task_id": task_id, "decision": "approve", "payload": {"approved_by": "tester"}},
        )
    events = drain_queue(queue)

    assert chat_response.status_code == 200
    assert chat_response.json()["status"] == "waiting_hitl"
    assert hitl_response.status_code == 200
    assert hitl_response.json() == {"status": "ok", "task_id": task_id, "decision": "approve"}
    task = await_sync(_load_task(runtime, task_id))
    assert task.status == "running"
    assert runtime["task_system"].waiting_hitl[task_id] == {
        "decision": "approve",
        "payload": {"approved_by": "tester"},
    }
    assert any(event.type == EventType.TASK_WAITING_HITL for event in runtime["event_bus"].events)
    assert any(event.type == EventType.HITL_FEEDBACK for event in runtime["event_bus"].events)
    assert [event["event"] for event in events] == ["message", "done"]
    assert events[1]["data"]["status"] == "waiting_hitl"


def test_integration_degraded_streaming_unavailable_but_chat_safe() -> None:
    app, _runtime = build_runtime_app(
        chat_response=(
            "<inner_thoughts>fallback direct reply</inner_thoughts>"
            "<action>direct_reply</action>"
            "<content>Safe degraded reply.</content>"
        ),
        agent_capability=0.0,
        streaming_disabled=True,
        vector_retriever=None,
        session_context_store=SimpleNamespace(
            append_message=_async_noop_message,
            get_recent_messages=_async_empty_messages,
            get_adaptations=_async_empty_adaptations,
        ),
    )

    with TestClient(app) as client:
        chat_response = client.post(
            "/chat",
            json={"text": "hello in degraded mode", "session_id": "session-1", "user_id": "user-1"},
        )
        stream_response = client.get("/chat/stream", params={"session_id": "session-1"})

    assert chat_response.status_code == 200
    assert chat_response.json()["reply"] == "Safe degraded reply."
    assert stream_response.status_code == 503
    assert stream_response.json() == {
        "error": {
            "code": "streaming_unavailable",
            "message": "Streaming is currently unavailable for this runtime.",
            "details": {"session_id": "session-1"},
        }
    }


async def _async_noop_message(user_id: str, session_id: str, message: dict[str, Any]) -> None:
    return None


async def _async_empty_messages(user_id: str, session_id: str) -> list[dict[str, Any]]:
    return []


async def _async_empty_adaptations(user_id: str, session_id: str) -> list[str]:
    return []


def drain_queue(queue: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def await_sync(awaitable: Any) -> Any:
    import asyncio

    return asyncio.run(awaitable)
