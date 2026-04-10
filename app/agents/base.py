"""Sub-agent contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.tasks.models import Task, TaskResult


class SubAgent(ABC):
    """Base contract for all task-executing sub-agents."""

    name: str
    domain: str
    task_store: Any = None

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """Execute a task and return a normalized result."""

    @abstractmethod
    async def estimate_capability(self, task: Task) -> float:
        """Return a 0..1 score using lightweight, no-network heuristics."""

    async def resume(self, task: Task, hitl_result: dict[str, Any]) -> TaskResult:
        """Resume a paused task; defaults to re-entering execute()."""

        task.metadata["hitl_result"] = hitl_result
        return await self.execute(task)

    async def cancel(self) -> None:
        """Release external resources during cancellation if needed."""

    async def emit_heartbeat(self, task: Task) -> None:
        """Refresh the task heartbeat and notify the store when available."""

        task.last_heartbeat_at = datetime.now(timezone.utc)
        if self.task_store is not None:
            await self.task_store.update_heartbeat(task.id, task.last_heartbeat_at)

