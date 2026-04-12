"""Nightly maintenance entrypoints for evolution subsystems."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any


class EvolutionScheduler:
    """Minimal maintenance scheduler shell for V1."""

    def __init__(
        self,
        *,
        core_memory_scheduler: Any | None = None,
        graph_store: Any | None = None,
        mid_term_memory_store: Any | None = None,
        proactivity_service: Any | None = None,
        platform_adapter: Any | None = None,
    ) -> None:
        self.core_memory_scheduler = core_memory_scheduler
        self.graph_store = graph_store
        self.mid_term_memory_store = mid_term_memory_store
        self.proactivity_service = proactivity_service
        self.platform_adapter = platform_adapter
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
            await self.run_proactivity_tick()
            if now.hour == 3 and now.minute == 0:
                await self.run_daily_maintenance()
                await asyncio.sleep(60)
            await asyncio.sleep(30)

    async def run_daily_maintenance(self) -> None:
        if self.mid_term_memory_store is not None:
            await self.mid_term_memory_store.apply_decay()
            await self.mid_term_memory_store.cleanup_expired()
        return None

    async def run_proactivity_tick(self) -> None:
        if self.proactivity_service is None or self.platform_adapter is None:
            return None
        connected_contexts = getattr(self.platform_adapter, "connected_contexts", lambda: [])()
        seen_users: set[str] = set()
        for ctx in connected_contexts:
            if ctx.user_id in seen_users:
                continue
            seen_users.add(ctx.user_id)
            await self.proactivity_service.deliver_follow_up(
                user_id=ctx.user_id,
                ctx=ctx,
                platform_adapter=self.platform_adapter,
            )
        return None
