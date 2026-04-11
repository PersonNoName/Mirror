from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.evolution.event_bus import Event, RedisStreamsEventBus
from app.runtime.bootstrap import RuntimeContext, bind_runtime_state
from app.tasks.models import Task, TaskResult
from app.tasks.outbox_relay import OutboxRelay
from app.tasks.worker import TaskWorker


class RecordingRedisClient:
    def __init__(self, fail_xadd: bool = False) -> None:
        self.fail_xadd = fail_xadd
        self.acks: list[tuple[str, str, str]] = []
        self.xadds: list[tuple[str, dict[str, object]]] = []

    async def xack(self, stream_name: str, group_name: str, delivery_id: str) -> None:
        self.acks.append((stream_name, group_name, delivery_id))

    async def xadd(self, topic: str, fields: dict[str, object]) -> None:
        if self.fail_xadd:
            raise RuntimeError("redis write failed")
        self.xadds.append((topic, fields))


class RecordingOutboxStore:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events or []
        self.published: list[str] = []
        self.retries: list[tuple[str, int, str | None]] = []

    async def list_pending(self) -> list[object]:
        return list(self.events)

    async def mark_published(self, event_id: str) -> None:
        self.published.append(event_id)

    async def schedule_retry(self, event_id: str, retry_count: int, error: str | None = None) -> None:
        self.retries.append((event_id, retry_count, error))


class RecordingIdempotencyStore:
    def __init__(self, claim_result: bool = True, fail_mark_done: bool = False) -> None:
        self.claim_result = claim_result
        self.fail_mark_done = fail_mark_done
        self.claims: list[tuple[str, str]] = []
        self.done: list[tuple[str, str]] = []

    async def claim(self, scope: str, key: str) -> bool:
        self.claims.append((scope, key))
        return self.claim_result

    async def mark_done(self, scope: str, key: str) -> None:
        if self.fail_mark_done:
            raise RuntimeError("mark done failed")
        self.done.append((scope, key))


class RecordingBlackboard:
    def __init__(self) -> None:
        self.failures: list[tuple[str, str, str]] = []

    async def on_task_complete(self, task: Task, result: dict[str, object]) -> None:
        return None

    async def on_task_failed(self, task: Task, error: str, status: str = "failed") -> None:
        self.failures.append((task.id, error, status))
        task.status = status


class RecordingTaskSystem:
    DISPATCH_STREAM = "stream:task:dispatch"
    RETRY_STREAM = "stream:task:retry"

    def __init__(self) -> None:
        self.redis_client = None
        self.retry_publishes: list[str] = []
        self.dlq_publishes: list[tuple[str, str]] = []

    async def publish_retry(self, task: Task) -> None:
        self.retry_publishes.append(task.id)

    async def publish_dlq(self, task: Task, error: str) -> None:
        self.dlq_publishes.append((task.id, error))

    @staticmethod
    def stream_for_agent(agent_name: str, base_stream: str | None = None) -> str:
        return f"{base_stream or 'stream'}:{agent_name}"

    @staticmethod
    def group_for_agent(agent_name: str) -> str:
        return f"group:{agent_name}"


class RecordingTaskStore:
    def __init__(self) -> None:
        self.updated: list[Task] = []

    async def update(self, task: Task) -> Task:
        self.updated.append(task)
        return task

    async def get(self, task_id: str) -> Task | None:
        return None


class SilentPlatformAdapter:
    async def send_outbound(self, ctx: object, message: object) -> None:
        return None


@pytest.mark.asyncio
async def test_event_bus_handler_failure_does_not_ack_message() -> None:
    redis = RecordingRedisClient()
    idempotency = RecordingIdempotencyStore()
    bus = RedisStreamsEventBus(redis_client=redis, outbox_store=object(), idempotency_store=idempotency)

    async def failing_handler(event: Event) -> None:
        raise RuntimeError("boom")

    await bus.subscribe("dialogue_ended", failing_handler)
    fields = {"payload": '{"event":{"id":"evt-1","type":"dialogue_ended","payload":{}}}'}

    await bus._handle_message("dialogue_ended", "stream:event:dialogue", "group:event:dialogue_ended", "1-0", fields)

    assert redis.acks == []
    assert idempotency.done == []


@pytest.mark.asyncio
async def test_event_bus_malformed_payload_is_acked() -> None:
    redis = RecordingRedisClient()
    bus = RedisStreamsEventBus(redis_client=redis, outbox_store=object(), idempotency_store=None)

    await bus._handle_message("dialogue_ended", "stream:event:dialogue", "group:event:dialogue_ended", "1-0", {"payload": "{bad"})

    assert redis.acks == [("stream:event:dialogue", "group:event:dialogue_ended", "1-0")]


@pytest.mark.asyncio
async def test_event_bus_duplicate_message_is_acked_without_processing() -> None:
    redis = RecordingRedisClient()
    idempotency = RecordingIdempotencyStore(claim_result=False)
    bus = RedisStreamsEventBus(redis_client=redis, outbox_store=object(), idempotency_store=idempotency)
    fields = {"payload": '{"event":{"id":"evt-2","type":"dialogue_ended","payload":{}}}'}

    await bus._handle_message("dialogue_ended", "stream:event:dialogue", "group:event:dialogue_ended", "2-0", fields)

    assert redis.acks == [("stream:event:dialogue", "group:event:dialogue_ended", "2-0")]


@pytest.mark.asyncio
async def test_outbox_relay_does_not_mark_published_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    event = SimpleNamespace(id="evt-1", topic="stream:test", payload={}, retry_count=0)
    store = RecordingOutboxStore(events=[event])
    relay = OutboxRelay(outbox_store=store, redis_client=None, interval_seconds=0)

    async def stop_after_first_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        await relay._run()

    assert store.published == []
    assert store.retries == []


@pytest.mark.asyncio
async def test_outbox_relay_schedules_retry_on_redis_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    event = SimpleNamespace(id="evt-2", topic="stream:test", payload={}, retry_count=0)
    store = RecordingOutboxStore(events=[event])
    relay = OutboxRelay(outbox_store=store, redis_client=RecordingRedisClient(fail_xadd=True), interval_seconds=0)

    async def stop_after_first_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", stop_after_first_sleep)

    with pytest.raises(asyncio.CancelledError):
        await relay._run()

    assert store.published == []
    assert store.retries == [("evt-2", 1, "redis write failed")]


@pytest.mark.asyncio
async def test_task_worker_preserves_interrupted_terminal_status() -> None:
    worker = TaskWorker(
        agent=SimpleNamespace(name="code_agent"),
        task_store=RecordingTaskStore(),
        task_system=RecordingTaskSystem(),
        blackboard=RecordingBlackboard(),
        platform_adapter=SilentPlatformAdapter(),
    )
    task = Task(id="task-1", status="running")

    await worker._handle_failure(task, "stopped", error_type="INTERRUPTED")

    assert worker.blackboard.failures == [("task-1", "stopped", "interrupted")]
    assert worker.task_system.dlq_publishes == [("task-1", "stopped")]


def test_bind_runtime_state_disables_streaming_when_redis_missing() -> None:
    app = FastAPI()
    runtime = RuntimeContext(
        redis_client=None,
        model_registry=object(),
        outbox_store=SimpleNamespace(),
        idempotency_store=SimpleNamespace(),
        core_memory_store=SimpleNamespace(),
        core_memory_cache=SimpleNamespace(),
        session_context_store=SimpleNamespace(),
        vector_retriever=None,
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
        skill_summary={},
        mcp_summary={},
        builtins_summary={},
        startup_degraded_reasons=["redis_unavailable"],
    )

    bind_runtime_state(app, runtime)

    assert app.state.streaming_disabled is True
    assert app.state.runtime is runtime
