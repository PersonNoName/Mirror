"""Hook registry contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import structlog


logger = structlog.get_logger(__name__)
HookHandler = Callable[..., Awaitable[None]]


class HookPoint(StrEnum):
    """Supported extension hook points."""

    PRE_REASON = "pre_reason"
    POST_REASON = "post_reason"
    PRE_TASK = "pre_task"
    POST_REPLY = "post_reply"


@dataclass(slots=True)
class HookDefinition:
    """Structured runtime representation for hook handlers."""

    hook_point: HookPoint
    handler: HookHandler
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


class HookRegistry:
    """Best-effort async hook registry."""

    def __init__(self) -> None:
        self._handlers: dict[HookPoint, list[HookDefinition]] = defaultdict(list)

    def register(
        self,
        hook_point: HookPoint,
        handler: HookHandler | None = None,
        *,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> HookHandler | Callable[[HookHandler], HookHandler]:
        """Register a hook directly or return a decorator."""

        if handler is None:
            def decorator(func: HookHandler) -> HookHandler:
                self._handlers[hook_point].append(
                    HookDefinition(
                        hook_point=hook_point,
                        handler=func,
                        source=source,
                        metadata=metadata or {},
                    )
                )
                return func

            return decorator

        self._handlers[hook_point].append(
            HookDefinition(
                hook_point=hook_point,
                handler=handler,
                source=source,
                metadata=metadata or {},
            )
        )
        return handler

    def get_handlers(self, hook_point: HookPoint) -> list[HookDefinition]:
        """Return a snapshot of handlers for a hook point."""

        return list(self._handlers.get(hook_point, []))

    async def trigger(self, hook_point: HookPoint, **payload: Any) -> None:
        """Run all handlers and swallow failures after logging them."""

        for definition in self.get_handlers(hook_point):
            try:
                await definition.handler(**payload)
            except Exception:
                logger.exception(
                    "hook_handler_failed",
                    hook_point=hook_point.value,
                    hook_source=definition.source,
                )


hook_registry = HookRegistry()
