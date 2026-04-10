"""In-process runtime event bus for foreground execution."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from app.evolution.event_bus import Event, EventBus


class InMemoryEventBus(EventBus):
    """Simple in-memory event bus for single-process runtime usage."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = defaultdict(list)

    async def emit(self, event: Event) -> None:
        for handler in list(self._handlers.get(event.type, [])):
            await handler(event)

    async def subscribe(self, event_type: str, handler: Any) -> None:
        self._handlers[event_type].append(handler)
