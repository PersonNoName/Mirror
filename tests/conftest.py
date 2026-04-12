from __future__ import annotations

from typing import Any

from app.memory import CoreMemory
from app.providers.base import ModelSpec


class DummyCoreMemoryCache:
    def __init__(self, core_memory: CoreMemory | None = None) -> None:
        self.core_memory = core_memory or CoreMemory()

    async def get(self, user_id: str) -> CoreMemory:
        return self.core_memory


class DummySessionContextStore:
    def __init__(
        self,
        recent_messages: list[dict[str, Any]] | None = None,
        adaptations: list[str] | None = None,
    ) -> None:
        self.recent_messages = recent_messages or []
        self.adaptations = adaptations or []

    async def get_recent_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        return list(self.recent_messages)

    async def get_adaptations(self, user_id: str, session_id: str) -> list[str]:
        return list(self.adaptations)

    async def set_adaptations(self, user_id: str, session_id: str, adaptations: list[str]) -> None:
        self.adaptations = list(adaptations)


class DummyVectorRetriever:
    def __init__(self, matches: list[dict[str, Any]] | None = None) -> None:
        self.matches = matches or []

    async def retrieve(self, user_id: str, query: str, limit: int = 8) -> dict[str, Any]:
        return {"matches": list(self.matches)}


class DummyMidTermMemoryStore:
    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = items or []
        self.degraded = False
        self.degraded_reason: str | None = None
        self.storage_source = "postgres"

    async def retrieve(self, user_id: str, query: str, limit: int = 5) -> list[Any]:
        return list(self.items)[:limit]

    async def list_items(self, *, user_id: str, include_expired: bool = False, statuses: set[str] | None = None) -> list[Any]:
        return list(self.items)

    async def suppress_related(
        self,
        *,
        user_id: str,
        memory_key: str | None = None,
        content: str | None = None,
        reason: str = "",
    ) -> list[str]:
        return [memory_key] if memory_key else []

    async def mark_promoted(self, *, user_id: str, memory_key: str, promoted_memory_key: str) -> None:
        return None


class DummyChatModel:
    def __init__(
        self,
        response: Any = None,
        error: Exception | None = None,
        stream_chunks: list[Any] | None = None,
        stream_error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.stream_chunks = stream_chunks
        self.stream_error = stream_error
        self.calls: list[list[dict[str, Any]]] = []
        self.stream_calls: list[list[dict[str, Any]]] = []

    async def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        return self.response

    async def stream(self, messages: list[dict[str, Any]], **kwargs: Any):
        self.stream_calls.append(messages)
        if self.stream_error is not None:
            raise self.stream_error
        if self.stream_chunks is None:
            raise NotImplementedError
        for chunk in self.stream_chunks:
            yield chunk


class DummyModelRegistry:
    def __init__(self, api_key: str | None = "test-key", chat_model: Any | None = None) -> None:
        self.specs = {
            "reasoning.main": ModelSpec(
                profile="reasoning.main",
                capability="chat",
                provider_type="openai_compatible",
                vendor="openai",
                model="gpt-test",
                base_url="https://example.com",
                api_key_ref=api_key,
            )
        }
        self._chat_model = chat_model or DummyChatModel()

    def chat(self, profile: str) -> Any:
        return self._chat_model


class DummyToolCatalog:
    def __init__(self, tools: list[dict[str, Any]] | None = None) -> None:
        self.tools = tools or []

    def describe_tools(self) -> list[dict[str, Any]]:
        return list(self.tools)


class RecordingPlatformAdapter:
    def __init__(self) -> None:
        self.outbound: list[tuple[Any, Any]] = []
        self.hitl: list[tuple[Any, Any]] = []

    async def send_outbound(self, ctx: Any, message: Any) -> None:
        self.outbound.append((ctx, message))

    async def send_hitl(self, ctx: Any, request: Any) -> None:
        self.hitl.append((ctx, request))


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


class RecordingHookRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, dict[str, Any]]] = []

    async def trigger(self, hook_point: Any, **payload: Any) -> None:
        self.calls.append((hook_point, payload))


class DummyBlackboard:
    def __init__(self) -> None:
        self.waiting_hitl: list[tuple[Any, Any]] = []
        self.assigned: list[Any] = []

    async def on_task_waiting_hitl(self, task: Any, request: Any) -> None:
        self.waiting_hitl.append((task, request))

    async def assign(self, task: Any) -> None:
        self.assigned.append(task)


class DummyTaskStore:
    def __init__(self) -> None:
        self.created: list[Any] = []
        self.updated: list[Any] = []

    async def create(self, task: Any) -> Any:
        self.created.append(task)
        return task

    async def update(self, task: Any) -> Any:
        self.updated.append(task)
        return task


class DummyOutboxStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def from_payload(self, topic: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        return (topic, payload)

    async def enqueue(self, event: tuple[str, dict[str, Any]]) -> None:
        self.events.append(event)
