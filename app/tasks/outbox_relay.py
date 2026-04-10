"""Relay outbox events into Redis Streams when available."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any


class OutboxRelay:
    """Best-effort outbox relay with graceful degradation."""

    def __init__(self, outbox_store: Any, redis_client: Any | None = None, interval_seconds: float = 1.0) -> None:
        self.outbox_store = outbox_store
        self.redis_client = redis_client
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None
        self.degraded = redis_client is None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            for event in await self.outbox_store.list_pending():
                if self.redis_client is not None:
                    try:
                        fields = self._build_stream_fields(event)
                        await self.redis_client.xadd(event.topic, fields)
                        await self.outbox_store.mark_published(event.id)
                    except Exception as exc:
                        await self.outbox_store.schedule_retry(
                            event.id,
                            event.retry_count + 1,
                            str(exc),
                        )
                        continue
                else:
                    await self.outbox_store.mark_published(event.id)
            await asyncio.sleep(self.interval_seconds)

    @staticmethod
    def _build_stream_fields(event: Any) -> dict[str, Any]:
        payload = dict(event.payload)
        event_payload = payload.get("event", {})
        task = payload.get("task", {})
        fields = {
            "event_id": event.id,
            "topic": event.topic,
            "task_id": str(task.get("id", "")),
            "assigned_to": str(task.get("assigned_to", "")),
            "intent": str(task.get("intent", "")),
            "event_type": str(event_payload.get("type", "")),
            "payload": json.dumps(payload, ensure_ascii=False, default=str),
        }
        error = event.payload.get("error")
        if error is not None:
            fields["error"] = str(error)
        return fields
