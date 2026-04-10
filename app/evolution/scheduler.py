"""Nightly maintenance entrypoints for evolution subsystems."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any


class EvolutionScheduler:
    """Minimal maintenance scheduler shell for V1."""

    def __init__(self, *, core_memory_scheduler: Any | None = None, graph_store: Any | None = None) -> None:
        self.core_memory_scheduler = core_memory_scheduler
        self.graph_store = graph_store
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
            now = datetime.now()
            if now.hour == 3 and now.minute == 0:
                await self.run_daily_maintenance()
                await asyncio.sleep(60)
            await asyncio.sleep(30)

    async def run_daily_maintenance(self) -> None:
        return None
