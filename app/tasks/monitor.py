"""Task monitor for heartbeat timeouts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any


class TaskMonitor:
    """Periodically mark stalled running tasks as failed."""

    def __init__(self, task_store: Any, blackboard: Any, interval_seconds: int = 10) -> None:
        self.task_store = task_store
        self.blackboard = blackboard
        self.interval_seconds = interval_seconds
        self._task: asyncio.Task[None] | None = None

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
            now = datetime.now(timezone.utc)
            for task in await self.task_store.get_by_status("running"):
                if (now - task.last_heartbeat_at).total_seconds() > task.heartbeat_timeout:
                    await self.blackboard.on_task_failed(task, "Agent Heartbeat Lost")
            await asyncio.sleep(self.interval_seconds)
