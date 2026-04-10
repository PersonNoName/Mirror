"""Relay outbox events into Redis Streams when available."""

from __future__ import annotations

import asyncio
from typing import Any


class OutboxRelay:
    """Best-effort outbox relay with graceful degradation."""

    def __init__(self, task_system: Any, redis_client: Any | None = None, interval_seconds: float = 1.0) -> None:
        self.task_system = task_system
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
            for event in list(self.task_system.outbox_events.values()):
                if event.status == "published":
                    continue
                if self.redis_client is not None:
                    await self.redis_client.xadd(event.topic, {"payload": str(event.payload), "event_id": event.id})
                event.status = "published"
                event.published_at = event.created_at
            await asyncio.sleep(self.interval_seconds)
