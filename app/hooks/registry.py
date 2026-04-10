"""Hook registry contracts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
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


class HookRegistry:
    """Best-effort async hook registry."""

    def __init__(self) -> None:
        self._handlers: dict[HookPoint, list[HookHandler]] = defaultdict(list)

    def register(self, hook_point: HookPoint, handler: HookHandler) -> None:
        """Register a handler for a specific hook point."""

        self._handlers[hook_point].append(handler)

    def get_handlers(self, hook_point: HookPoint) -> list[HookHandler]:
        """Return a snapshot of handlers for a hook point."""

        return list(self._handlers.get(hook_point, []))

    async def trigger(self, hook_point: HookPoint, **payload: Any) -> None:
        """Run all handlers and swallow failures after logging them."""

        for handler in self.get_handlers(hook_point):
            try:
                await handler(**payload)
            except Exception:
                logger.exception("hook_handler_failed", hook_point=hook_point.value)


hook_registry = HookRegistry()
