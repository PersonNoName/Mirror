"""Blackboard service for task assignment and lifecycle callbacks."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.evolution.event_bus import Event, EventType
from app.tasks.models import Task


class Blackboard:
    """Stateless coordinator over task store, registry, and event bus."""

    def __init__(self, task_store: Any, task_system: Any, agent_registry: Any, event_bus: Any) -> None:
        self.task_store = task_store
        self.task_system = task_system
        self.agent_registry = agent_registry
        self.event_bus = event_bus

    async def evaluate_agents(self, task: Task) -> tuple[Any | None, float]:
        best_agent = None
        best_score = 0.0
        for agent in self.agent_registry.all():
            score = await agent.estimate_capability(task)
            if score > best_score:
                best_agent = agent
                best_score = score
        return best_agent, best_score

    async def assign(self, task: Task) -> None:
        task.status = "running"
        await self.task_store.update(task)
        await self.task_system.publish_dispatch(task)

    async def on_task_waiting_hitl(self, task: Task, request: Any) -> None:
        task.status = "waiting_hitl"
        task.metadata["hitl_request"] = {
            "task_id": request.task_id,
            "title": request.title,
            "description": request.description,
            "options": list(getattr(request, "options", ["approve", "reject"])),
            "risk_level": getattr(request, "risk_level", "medium"),
            "metadata": dict(getattr(request, "metadata", {})),
        }
        await self.task_store.update(task)
        await self.event_bus.emit(
            Event(
                type=EventType.TASK_WAITING_HITL,
                payload={"task_id": task.id, "request": task.metadata["hitl_request"]},
            )
        )

    async def resume(self, task_id: str, hitl_result: dict[str, Any]) -> Task | None:
        task = await self.task_store.get(task_id)
        if task is None:
            return None
        task.metadata["hitl_result"] = hitl_result
        task.status = "running"
        await self.task_store.update(task)
        return task

    async def on_task_complete(self, task: Task, result: dict[str, Any] | None = None) -> None:
        task.status = "done"
        task.result = result
        await self.task_store.update(task)
        await self.event_bus.emit(
            Event(type=EventType.TASK_COMPLETED, payload={"task_id": task.id, "result": result or {}})
        )

    async def on_task_failed(self, task: Task, error: str) -> None:
        task.status = "failed"
        task.error_trace = error
        await self.task_store.update(task)
        await self.event_bus.emit(
            Event(type=EventType.TASK_FAILED, payload={"task_id": task.id, "error": error})
        )

    async def terminate_agent(self, agent_name: str) -> None:
        agent = self.agent_registry.get(agent_name)
        if agent is None:
            return
        await agent.cancel()
