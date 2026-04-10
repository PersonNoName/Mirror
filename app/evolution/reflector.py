"""Meta-cognition reflector for task outcomes."""

from __future__ import annotations

from typing import Any

from app.evolution.event_bus import Event, EventType
from app.evolution.helpers import extract_json
from app.providers.openai_compat import ProviderRequestError
from app.tasks.models import Lesson


class MetaCognitionReflector:
    """Generate lessons from completed or failed tasks."""

    def __init__(self, *, model_registry: Any, task_store: Any, event_bus: Any) -> None:
        self.model_registry = model_registry
        self.task_store = task_store
        self.event_bus = event_bus
        self.circuit_breaker: Any | None = None

    async def handle_task_completed(self, event: Event) -> None:
        await self._reflect(event, "done")

    async def handle_task_failed(self, event: Event) -> None:
        await self._reflect(event, "failed")

    async def _reflect(self, event: Event, outcome: str) -> None:
        task = await self.task_store.get(event.payload.get("task_id", ""))
        if task is None:
            return
        lesson = await self.reflect(task, outcome=outcome)
        if lesson is None or lesson.confidence < 0.5:
            return
        await self.event_bus.emit(
            Event(
                type=EventType.LESSON_GENERATED,
                payload={"lesson": self._lesson_payload(lesson)},
            )
        )

    async def reflect(self, task: Any, outcome: str) -> Lesson | None:
        try:
            generate = self.model_registry.chat("lite.extraction").generate
            payload = [
                {
                    "role": "system",
                    "content": (
                        "根据任务输入、结果和错误生成一条 Lesson，返回 JSON，字段包括 "
                        "root_cause, lesson, is_agent_capability_issue, subject, relation, object, confidence."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"task_snapshot={task.prompt_snapshot}\n"
                        f"task_result={task.result}\n"
                        f"error_trace={task.error_trace}\n"
                        f"domain={task.metadata.get('domain', task.assigned_to or 'general')}"
                    ),
                },
            ]
            if self.circuit_breaker is None:
                response = await generate(payload)
            else:
                response = await self.circuit_breaker.call("evolution_lite_extraction", generate, payload)
        except (ProviderRequestError, KeyError, NotImplementedError, ValueError):
            return None
        data = extract_json(response, {})
        if not isinstance(data, dict):
            return None
        return Lesson(
            source_task_id=task.id,
            user_id=task.metadata.get("user_id", ""),
            domain=task.metadata.get("domain", task.assigned_to or "general"),
            outcome=outcome,
            category="reflection",
            summary=data.get("lesson", ""),
            root_cause=data.get("root_cause", ""),
            lesson_text=data.get("lesson", ""),
            is_agent_capability_issue=bool(data.get("is_agent_capability_issue", False)),
            subject=data.get("subject"),
            relation=data.get("relation"),
            object=data.get("object"),
            details={"task_id": task.id, "task_result": task.result, "error_trace": task.error_trace},
            confidence=float(data.get("confidence", 0.0)),
        )

    @staticmethod
    def _lesson_payload(lesson: Lesson) -> dict[str, Any]:
        return {
            "id": lesson.id,
            "source_task_id": lesson.source_task_id,
            "user_id": lesson.user_id,
            "domain": lesson.domain,
            "outcome": lesson.outcome,
            "category": lesson.category,
            "summary": lesson.summary,
            "root_cause": lesson.root_cause,
            "lesson_text": lesson.lesson_text,
            "is_agent_capability_issue": lesson.is_agent_capability_issue,
            "subject": lesson.subject,
            "relation": lesson.relation,
            "object": lesson.object,
            "details": lesson.details,
            "confidence": lesson.confidence,
        }
