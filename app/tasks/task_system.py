"""Task creation and dispatch facade."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from redis.asyncio import Redis

from app.platform.base import InboundMessage
from app.soul.models import Action
from app.tasks.models import Task


class TaskSystem:
    """Facade for task creation and asynchronous dispatch."""

    DISPATCH_STREAM = "stream:task:dispatch"
    RETRY_STREAM = "stream:task:retry"
    DLQ_STREAM = "stream:task:dlq"

    def __init__(self, task_store: Any, outbox_store: Any, redis_client: Redis | None = None) -> None:
        self.task_store = task_store
        self.outbox_store = outbox_store
        self.redis_client = redis_client
        self.waiting_hitl: dict[str, dict[str, Any]] = {}
        self._hitl_waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def create_task_from_action(self, action: Action, inbound_message: InboundMessage) -> Task:
        task = Task(
            intent=str(action.content),
            prompt_snapshot=inbound_message.text,
            dispatch_stream=self.DISPATCH_STREAM,
            metadata={
                "user_id": inbound_message.user_id,
                "session_id": inbound_message.session_id,
                "action_type": action.type,
            },
        )
        await self.task_store.create(task)
        return task

    async def update_task(self, task: Task) -> Task:
        return await self.task_store.update(task)

    async def publish_dispatch(self, task: Task) -> None:
        await self.outbox_store.enqueue(
            self.outbox_store.from_payload(task.dispatch_stream, {"task": asdict(task)})
        )

    async def publish_retry(self, task: Task) -> None:
        await self.outbox_store.enqueue(
            self.outbox_store.from_payload(
                self.stream_for_agent(task.assigned_to, self.RETRY_STREAM),
                {"task": asdict(task)},
            )
        )

    async def publish_dlq(self, task: Task, error: str) -> None:
        await self.outbox_store.enqueue(
            self.outbox_store.from_payload(
                self.stream_for_agent(task.assigned_to, self.DLQ_STREAM),
                {"task": asdict(task), "error": error},
            )
        )

    async def ensure_consumer_group(self, agent_name: str, stream_kind: str = DISPATCH_STREAM) -> None:
        if self.redis_client is None:
            return
        stream = self.stream_for_agent(agent_name, stream_kind)
        group = self.group_for_agent(agent_name)
        try:
            await self.redis_client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def ensure_worker_groups(self, agent_name: str) -> None:
        await self.ensure_consumer_group(agent_name, self.DISPATCH_STREAM)
        await self.ensure_consumer_group(agent_name, self.RETRY_STREAM)
        await self.ensure_consumer_group(agent_name, self.DLQ_STREAM)

    async def register_hitl_response(self, task_id: str, decision: str, payload: dict[str, Any] | None = None) -> None:
        response = {"decision": decision, "payload": payload or {}}
        self.waiting_hitl[task_id] = response
        waiter = self._hitl_waiters.pop(task_id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(response)

    async def wait_for_hitl_response(self, task_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        existing = self.waiting_hitl.pop(task_id, None)
        if existing is not None:
            return existing
        future = asyncio.get_running_loop().create_future()
        self._hitl_waiters[task_id] = future
        try:
            if timeout_seconds is None:
                return await future
            return await asyncio.wait_for(future, timeout_seconds)
        finally:
            self._hitl_waiters.pop(task_id, None)

    @classmethod
    def stream_for_agent(cls, agent_name: str, base_stream: str | None = None) -> str:
        stream = base_stream or cls.DISPATCH_STREAM
        return f"{stream}:{agent_name}"

    @staticmethod
    def group_for_agent(agent_name: str) -> str:
        return f"group:{agent_name}"
