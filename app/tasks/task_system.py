"""Task creation and dispatch facade."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from redis.asyncio import Redis

from app.infra.outbox import OutboxEvent
from app.platform.base import InboundMessage
from app.soul.models import Action
from app.tasks.models import Task


class TaskSystem:
    """Facade for task creation and asynchronous dispatch."""

    DISPATCH_STREAM = "stream:task:dispatch"
    RETRY_STREAM = "stream:task:retry"
    DLQ_STREAM = "stream:task:dlq"

    def __init__(self, task_store: Any, redis_client: Redis | None = None) -> None:
        self.task_store = task_store
        self.redis_client = redis_client
        self.outbox_events: dict[str, OutboxEvent] = {}
        self.waiting_hitl: dict[str, dict[str, Any]] = {}

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
        event = OutboxEvent(
            topic=self.DISPATCH_STREAM,
            payload={"task": asdict(task)},
        )
        self.outbox_events[event.id] = event
        return task

    async def update_task(self, task: Task) -> Task:
        return await self.task_store.update(task)

    async def publish_dispatch(self, task: Task) -> None:
        if self.redis_client is None:
            return
        await self.redis_client.xadd(
            self.DISPATCH_STREAM,
            {"task_id": task.id, "assigned_to": task.assigned_to, "intent": task.intent},
        )

    async def register_hitl_response(self, task_id: str, decision: str, payload: dict[str, Any] | None = None) -> None:
        self.waiting_hitl[task_id] = {"decision": decision, "payload": payload or {}}
