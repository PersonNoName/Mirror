"""Platform-facing data contracts and adapter abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class PlatformContext:
    """Normalized platform session context shared by the core runtime."""

    platform: str
    user_id: str
    session_id: str
    platform_conversation_id: str | None = None
    capabilities: set[str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class InboundMessage:
    """Standardized inbound message emitted by a platform adapter."""

    text: str
    user_id: str
    session_id: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    platform_ctx: PlatformContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessage:
    """Standardized outbound message consumed by a platform adapter."""

    type: Literal["text", "stream", "card", "hitl_request"] = "text"
    content: Any = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HitlRequest:
    """Structured human-in-the-loop request."""

    task_id: str
    title: str
    description: str
    options: list[str] = field(default_factory=lambda: ["approve", "reject"])
    risk_level: Literal["low", "medium", "high"] = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)


class PlatformAdapter(ABC):
    """Abstract platform adapter contract."""

    @abstractmethod
    async def normalize_inbound(self, raw_event: Any) -> InboundMessage:
        """Normalize a raw platform event into the shared message shape."""

    @abstractmethod
    async def send_outbound(
        self,
        ctx: PlatformContext,
        message: OutboundMessage,
    ) -> None:
        """Send a normalized outbound message back to the platform."""

    @abstractmethod
    async def send_hitl(self, ctx: PlatformContext, req: HitlRequest) -> None:
        """Send a HITL request through the platform's interaction surface."""

    async def edit_message(
        self,
        ctx: PlatformContext,
        message_id: str,
        patch: dict[str, Any],
    ) -> None:
        """Optional edit hook for platforms that support message mutation."""

