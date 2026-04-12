from __future__ import annotations

import asyncio
import json
import logging
import sys
from io import StringIO
from types import SimpleNamespace

import pytest

from app.evolution.event_bus import Event, RedisStreamsEventBus
from app.logging import configure_logging
from app.observability import ChatTraceService
from app.runtime.bootstrap import RuntimeContext
from app.soul.models import Action
from app.soul.router import ActionRouter
from app.tasks.blackboard import Blackboard
from app.tasks.models import Task
from app.tasks.outbox_relay import OutboxRelay
from app.tasks.worker import TaskWorker
from app.tools import ToolRegistry

from tests.conftest import RecordingEventBus
from tests.test_failure_semantics import (
    RecordingBlackboard,
    RecordingOutboxStore,
    RecordingRedisClient,
    RecordingTaskStore,
    RecordingTaskSystem,
    SilentPlatformAdapter,
)


class StdoutCapture:
    def __enter__(self) -> StringIO:
        self._original = sys.stdout
        self.stream = StringIO()
        sys.stdout = self.stream
        return self.stream

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        sys.stdout = self._original


def configure_test_logging() -> None:
    stream = StringIO()
    configure_logging("INFO")
    logger = logging.getLogger()
    logger.handlers = [logging.StreamHandler(stream)]
    logger.setLevel(logging.INFO)


class DummyAgentRegistry:
    def all(self) -> list[object]:
        return []


class PublishDispatchTaskSystem:
    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def publish_dispatch(self, task: Task) -> None:
        self.dispatched.append(task.id)


@pytest.mark.asyncio
async def test_blackboard_assign_logs_task_assigned() -> None:
    configure_test_logging()
    task_store = RecordingTaskStore()
    task_system = PublishDispatchTaskSystem()
    blackboard = Blackboard(
        task_store=task_store,
        task_system=task_system,
        agent_registry=DummyAgentRegistry(),
        event_bus=RecordingEventBus(),
    )
    task = Task(id="task-assign", assigned_to="code_agent", dispatch_stream="stream:task:dispatch", consumer_group="group:code_agent")

    with StdoutCapture() as stream:
        await blackboard.assign(task)

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["event"] == "task_assigned"
    assert payload["task_id"] == "task-assign"


@pytest.mark.asyncio
async def test_task_worker_logs_retry_and_dlq_events() -> None:
    configure_test_logging()
    retry_system = RecordingTaskSystem()
    worker = TaskWorker(
        agent=SimpleNamespace(name="code_agent"),
        task_store=RecordingTaskStore(),
        task_system=retry_system,
        blackboard=RecordingBlackboard(),
        platform_adapter=SilentPlatformAdapter(),
    )
    with StdoutCapture() as stream:
        retry_task = Task(id="task-retry", status="running")
        await worker._handle_failure(retry_task, "boom", error_type="RETRYABLE")

        failed_task = Task(id="task-dlq", status="running", retry_count=2, max_retries=2)
        await worker._handle_failure(failed_task, "fatal", error_type="FATAL")

    events = [json.loads(line)["event"] for line in stream.getvalue().strip().splitlines()]
    assert "task_retry_scheduled" in events
    assert "task_dlq_published" in events


@pytest.mark.asyncio
async def test_outbox_relay_logs_publish_and_degraded_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_test_logging()

    event_ok = SimpleNamespace(id="evt-ok", topic="stream:test", payload={}, retry_count=0)
    store_ok = RecordingOutboxStore(events=[event_ok])
    relay_ok = OutboxRelay(outbox_store=store_ok, redis_client=RecordingRedisClient(), interval_seconds=0)

    async def stop_after_first_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_first_sleep)
    with StdoutCapture() as stream:
        with pytest.raises(asyncio.CancelledError):
            await relay_ok._run()

        event_skip = SimpleNamespace(id="evt-skip", topic="stream:test", payload={}, retry_count=0)
        store_skip = RecordingOutboxStore(events=[event_skip])
        relay_skip = OutboxRelay(outbox_store=store_skip, redis_client=None, interval_seconds=0)
        with pytest.raises(asyncio.CancelledError):
            await relay_skip._run()

    events = [json.loads(line)["event"] for line in stream.getvalue().strip().splitlines()]
    assert "outbox_relay_published" in events
    assert "outbox_relay_publish_skipped" in events


@pytest.mark.asyncio
async def test_event_bus_logs_handler_failure() -> None:
    configure_test_logging()
    redis = RecordingRedisClient()
    bus = RedisStreamsEventBus(redis_client=redis, outbox_store=object(), idempotency_store=None)

    async def failing_handler(event: Event) -> None:
        raise RuntimeError("boom")

    await bus.subscribe("dialogue_ended", failing_handler)
    fields = {"payload": '{"event":{"id":"evt-log","type":"dialogue_ended","payload":{}}}'}
    with StdoutCapture() as stream:
        await bus._handle_message("dialogue_ended", "stream:event:dialogue", "group:event:dialogue_ended", "1-0", fields)

    payloads = [json.loads(line) for line in stream.getvalue().strip().splitlines()]
    failure = next(item for item in payloads if item["event"] == "event_handler_failed")
    summary = next(item for item in payloads if item["event"] == "event_processed_with_handler_failures")
    assert failure["event_id"] == "evt-log"
    assert failure["handler"] == "failing_handler"
    assert "exception" in failure
    assert summary["failed_handlers"] == ["failing_handler"]


@pytest.mark.asyncio
async def test_action_router_logs_tool_invocation_failure() -> None:
    configure_test_logging()
    registry = ToolRegistry()
    router = ActionRouter(
        platform_adapter=SilentPlatformAdapter(),
        event_bus=RecordingEventBus(),
        blackboard=SimpleNamespace(),
        task_system=SimpleNamespace(),
        tool_registry=registry,
    )
    inbound = SimpleNamespace(
        text="use tool",
        user_id="user-1",
        session_id="session-1",
        platform_ctx=SimpleNamespace(),
    )

    with StdoutCapture() as stream:
        await router._handle_tool_call(Action(type="tool_call", content='{"name":"missing","arguments":{}}'), inbound)

    payload = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert payload["event"] == "tool_invocation_failed"
    assert payload["tool_name"] == "missing"


def test_runtime_health_snapshot_includes_observability_fields() -> None:
    runtime = RuntimeContext(
        redis_client=None,
        model_registry=object(),
        outbox_store=SimpleNamespace(),
        idempotency_store=SimpleNamespace(),
        core_memory_store=SimpleNamespace(),
        core_memory_cache=SimpleNamespace(),
        session_context_store=SimpleNamespace(),
        mid_term_memory_store=SimpleNamespace(degraded=False, degraded_reason=None, storage_source="postgres"),
        vector_retriever=None,
        graph_store=None,
        event_bus=SimpleNamespace(degraded=True),
        event_bus_event_factory=lambda event_type, payload: (event_type, payload),
        core_memory_scheduler=SimpleNamespace(),
        evolution_journal=SimpleNamespace(),
        evolution_candidate_manager=SimpleNamespace(
            summary=lambda: {
                "pending_candidate_count": 1,
                "high_risk_pending_count": 0,
                "recent_reverted_count": 2,
                "degraded": False,
            }
        ),
        relationship_state_machine=SimpleNamespace(degraded=False),
        proactivity_service=SimpleNamespace(
            degraded=False,
            summary=lambda: {
                "gentle_proactivity_enabled": True,
                "gentle_proactivity_degraded": False,
                "status": "ok",
            },
        ),
        memory_governance_service=SimpleNamespace(degraded=False),
        personality_evolver=SimpleNamespace(),
        observer=SimpleNamespace(),
        reflector=SimpleNamespace(),
        cognition_updater=SimpleNamespace(),
        evolution_scheduler=SimpleNamespace(_task=None),
        task_store=SimpleNamespace(degraded=True),
        task_system=SimpleNamespace(),
        blackboard=SimpleNamespace(),
        outbox_relay=SimpleNamespace(degraded=True),
        task_monitor=SimpleNamespace(),
        worker_manager=SimpleNamespace(workers=[SimpleNamespace(degraded=True), SimpleNamespace(degraded=False)]),
        web_platform=SimpleNamespace(),
        soul_engine=SimpleNamespace(),
        action_router=SimpleNamespace(),
        skill_loader=SimpleNamespace(),
        mcp_adapter=SimpleNamespace(),
        chat_trace_service=ChatTraceService(),
        skill_summary={"loaded": [1, 2], "skipped": [3], "failed": []},
        mcp_summary={"loaded": [], "skipped": [1], "failed": [2, 3]},
        builtins_summary={},
        startup_degraded_reasons=["redis_unavailable", "postgres_unavailable"],
    )

    health = runtime.health_snapshot()

    assert health["streaming_available"] is False
    assert health["subsystems"]["redis"]["reason"] == "redis_unavailable"
    assert health["subsystems"]["worker_manager"]["workers"] == 2
    assert health["subsystems"]["worker_manager"]["degraded_workers"] == 1
    assert health["subsystems"]["mid_term_memory"]["reason"] is None
    assert health["subsystems"]["skill_loader"]["loaded_count"] == 2
    assert health["subsystems"]["mcp_loader"]["failed_count"] == 2
    assert health["subsystems"]["evolution_pipeline"]["pending_candidate_count"] == 1
    assert health["subsystems"]["relationship_stage"]["relationship_stage_enabled"] is True
    assert health["subsystems"]["gentle_proactivity"]["gentle_proactivity_enabled"] is True
    assert health["subsystems"]["memory_governance"]["memory_governance_enabled"] is True


@pytest.mark.asyncio
async def test_runtime_health_snapshot_async_reports_qdrant_probe_failure() -> None:
    runtime = RuntimeContext(
        redis_client=None,
        model_registry=object(),
        outbox_store=SimpleNamespace(),
        idempotency_store=SimpleNamespace(),
        core_memory_store=SimpleNamespace(),
        core_memory_cache=SimpleNamespace(),
        session_context_store=SimpleNamespace(),
        mid_term_memory_store=SimpleNamespace(degraded=False, degraded_reason=None, storage_source="postgres"),
        vector_retriever=SimpleNamespace(ping=lambda: _async_tuple(False, "qdrant_bad_gateway")),
        graph_store=None,
        event_bus=SimpleNamespace(degraded=True),
        event_bus_event_factory=lambda event_type, payload: (event_type, payload),
        core_memory_scheduler=SimpleNamespace(),
        evolution_journal=SimpleNamespace(),
        evolution_candidate_manager=SimpleNamespace(
            summary=lambda: {
                "pending_candidate_count": 0,
                "high_risk_pending_count": 0,
                "recent_reverted_count": 0,
                "degraded": False,
            }
        ),
        relationship_state_machine=SimpleNamespace(degraded=False),
        proactivity_service=SimpleNamespace(
            degraded=False,
            summary=lambda: {
                "gentle_proactivity_enabled": True,
                "gentle_proactivity_degraded": False,
                "status": "ok",
            },
        ),
        memory_governance_service=SimpleNamespace(degraded=False),
        personality_evolver=SimpleNamespace(),
        observer=SimpleNamespace(),
        reflector=SimpleNamespace(),
        cognition_updater=SimpleNamespace(),
        evolution_scheduler=SimpleNamespace(_task=None),
        task_store=SimpleNamespace(degraded=True),
        task_system=SimpleNamespace(),
        blackboard=SimpleNamespace(),
        outbox_relay=SimpleNamespace(degraded=True),
        task_monitor=SimpleNamespace(),
        worker_manager=SimpleNamespace(workers=[]),
        web_platform=SimpleNamespace(),
        soul_engine=SimpleNamespace(),
        action_router=SimpleNamespace(),
        skill_loader=SimpleNamespace(),
        mcp_adapter=SimpleNamespace(),
        chat_trace_service=ChatTraceService(),
        skill_summary={"loaded": [], "skipped": [], "failed": []},
        mcp_summary={"loaded": [], "skipped": [], "failed": []},
        builtins_summary={},
        startup_degraded_reasons=[],
    )

    health = await runtime.health_snapshot_async()

    assert health["status"] == "degraded"
    assert health["subsystems"]["qdrant"]["status"] == "degraded"
    assert health["subsystems"]["qdrant"]["reason"] == "qdrant_bad_gateway"


async def _async_tuple(ok: bool, reason: str | None) -> tuple[bool, str | None]:
    return ok, reason
