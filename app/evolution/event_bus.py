"""Redis Streams event bus and shared evolution data models."""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog


logger = structlog.get_logger(__name__)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventType:
    DIALOGUE_ENDED = "dialogue_ended"
    OBSERVATION_DONE = "observation_done"
    LESSON_GENERATED = "lesson_generated"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_WAITING_HITL = "task_waiting_hitl"
    HITL_FEEDBACK = "hitl_feedback"
    EVOLUTION_DONE = "evolution_done"

    ALL = frozenset(
        {
            DIALOGUE_ENDED,
            OBSERVATION_DONE,
            LESSON_GENERATED,
            TASK_COMPLETED,
            TASK_FAILED,
            TASK_WAITING_HITL,
            HITL_FEEDBACK,
            EVOLUTION_DONE,
        }
    )


EVENT_STREAMS = {
    EventType.DIALOGUE_ENDED: "stream:event:dialogue",
    EventType.OBSERVATION_DONE: "stream:event:evolution",
    EventType.LESSON_GENERATED: "stream:event:evolution",
    EventType.TASK_COMPLETED: "stream:event:task_result",
    EventType.TASK_FAILED: "stream:event:task_result",
    EventType.TASK_WAITING_HITL: "stream:event:task_result",
    EventType.HITL_FEEDBACK: "stream:event:dialogue",
    EventType.EVOLUTION_DONE: "stream:event:evolution",
}

LOW_PRIORITY_STREAM = "stream:event:low_priority"
LOW_PRIORITY_TYPES = frozenset({EventType.OBSERVATION_DONE})


@dataclass(slots=True)
class Event:
    type: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    priority: int = 1
    stream_name: str = ""
    delivery_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InteractionSignal:
    signal_type: str
    user_id: str
    session_id: str
    content: str
    confidence: float = 0.0
    source_event_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvolutionEntry:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    event_type: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)


class EventBus(ABC):
    @abstractmethod
    async def emit(self, event: Event) -> None:
        pass

    @abstractmethod
    async def subscribe(self, event_type: str, handler: Any) -> None:
        pass

    @abstractmethod
    async def ack(self, stream_name: str, delivery_id: str) -> None:
        pass

    @abstractmethod
    async def retry(self, event: Event) -> None:
        pass

    @abstractmethod
    async def start(self) -> None:
        pass

    @abstractmethod
    async def stop(self) -> None:
        pass


class RedisStreamsEventBus(EventBus):
    """Redis Streams backed bus with graceful degradation."""

    def __init__(
        self,
        redis_client: Any | None,
        outbox_store: Any,
        *,
        idempotency_store: Any | None = None,
        consumer_name: str = "evolution-runtime",
        max_queue_depth: int = 1000,
    ) -> None:
        self.redis_client = redis_client
        self.outbox_store = outbox_store
        self.idempotency_store = idempotency_store
        self.consumer_name = consumer_name
        self.max_queue_depth = max_queue_depth
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = defaultdict(list)
        self._tasks: list[asyncio.Task[None]] = []
        self.degraded = redis_client is None

    async def emit(self, event: Event) -> None:
        event.stream_name = self.stream_for_type(event.type)
        await self.outbox_store.enqueue(
            self.outbox_store.from_payload(event.stream_name, {"event": self._serialize_event(event)})
        )

    async def subscribe(self, event_type: str, handler: Any) -> None:
        self._handlers[event_type].append(handler)

    async def ack(self, stream_name: str, delivery_id: str) -> None:
        if self.degraded or not delivery_id:
            return
        await self.redis_client.xack(stream_name, self.group_for_type(self._event_type_for_stream(stream_name)), delivery_id)

    async def retry(self, event: Event) -> None:
        await self.emit(event)

    async def start(self) -> None:
        if self.degraded:
            logger.warning("event_bus_degraded", reason="redis_unavailable")
            return
        event_types = [event_type for event_type, handlers in self._handlers.items() if handlers]
        for event_type in event_types:
            stream_name = self.stream_for_type(event_type)
            group_name = self.group_for_type(event_type)
            try:
                await self.redis_client.xgroup_create(stream_name, group_name, id="0", mkstream=True)
            except Exception as exc:
                if "BUSYGROUP" not in str(exc):
                    raise
            self._tasks.append(asyncio.create_task(self._consume(event_type, stream_name, group_name)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _consume(self, event_type: str, stream_name: str, group_name: str) -> None:
        while True:
            await self._recover_pending(event_type, stream_name, group_name)
            entries = await self.redis_client.xreadgroup(
                groupname=group_name,
                consumername=self.consumer_name,
                streams={stream_name: ">"},
                count=20,
                block=5000,
            )
            for _, messages in entries:
                for delivery_id, fields in messages:
                    await self._handle_message(event_type, stream_name, group_name, delivery_id, fields)

    async def _recover_pending(self, event_type: str, stream_name: str, group_name: str) -> None:
        try:
            _, claimed, _ = await self.redis_client.xautoclaim(
                name=stream_name,
                groupname=group_name,
                consumername=self.consumer_name,
                min_idle_time=30_000,
                start_id="0-0",
                count=20,
            )
        except Exception:
            return
        for delivery_id, fields in claimed:
            await self._handle_message(event_type, stream_name, group_name, delivery_id, fields)

    async def _handle_message(
        self,
        event_type: str,
        stream_name: str,
        group_name: str,
        delivery_id: str,
        fields: dict[str, Any],
    ) -> None:
        try:
            event = self._deserialize_event(fields, stream_name, delivery_id)
        except Exception:
            logger.exception(
                "event_deserialize_failed",
                event_type=event_type,
                stream_name=stream_name,
                delivery_id=str(delivery_id),
            )
            await self.redis_client.xack(stream_name, group_name, delivery_id)
            return

        scope = f"event_consumer:{event_type}"
        if self.idempotency_store is not None:
            try:
                claimed = await self.idempotency_store.claim(scope, event.id)
            except Exception:
                logger.exception(
                    "event_idempotency_claim_failed",
                    event_type=event_type,
                    stream_name=stream_name,
                    delivery_id=str(delivery_id),
                    event_id=event.id,
                )
                return
            if not claimed:
                await self.redis_client.xack(stream_name, group_name, delivery_id)
                return
        try:
            for handler in list(self._handlers.get(event_type, [])):
                await handler(event)
        except Exception:
            logger.exception(
                "event_handler_failed",
                event_type=event_type,
                stream_name=stream_name,
                delivery_id=str(delivery_id),
                event_id=event.id,
            )
            return
        if self.idempotency_store is not None:
            try:
                await self.idempotency_store.mark_done(scope, event.id)
            except Exception:
                logger.exception(
                    "event_idempotency_mark_done_failed",
                    event_type=event_type,
                    stream_name=stream_name,
                    delivery_id=str(delivery_id),
                    event_id=event.id,
                )
                return
        await self.redis_client.xack(stream_name, group_name, delivery_id)

    @staticmethod
    def stream_for_type(event_type: str) -> str:
        return EVENT_STREAMS.get(event_type, LOW_PRIORITY_STREAM if event_type in LOW_PRIORITY_TYPES else "stream:event:evolution")

    @staticmethod
    def group_for_type(event_type: str) -> str:
        return f"group:event:{event_type}"

    @staticmethod
    def _serialize_event(event: Event) -> dict[str, Any]:
        payload = asdict(event)
        payload["created_at"] = event.created_at.isoformat()
        return payload

    @staticmethod
    def _deserialize_event(fields: dict[str, Any], stream_name: str, delivery_id: str) -> Event:
        raw_payload = fields.get("payload", "{}")
        if isinstance(raw_payload, bytes):
            raw_payload = raw_payload.decode()
        payload = json.loads(raw_payload)
        event_payload = dict(payload.get("event", {}))
        created_at = event_payload.get("created_at")
        return Event(
            id=event_payload.get("id", str(uuid4())),
            type=event_payload.get("type", fields.get("event_type", "")),
            payload=dict(event_payload.get("payload", {})),
            priority=int(event_payload.get("priority", 1)),
            stream_name=stream_name,
            delivery_id=str(delivery_id),
            created_at=datetime.fromisoformat(created_at) if created_at else utc_now(),
            metadata=dict(event_payload.get("metadata", {})),
        )

    @staticmethod
    def _event_type_for_stream(stream_name: str) -> str:
        for event_type, candidate in EVENT_STREAMS.items():
            if candidate == stream_name:
                return event_type
        return EventType.EVOLUTION_DONE
