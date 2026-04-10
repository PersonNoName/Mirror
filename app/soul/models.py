"""Foreground reasoning action models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ActionType = Literal["direct_reply", "tool_call", "publish_task", "hitl_relay"]


@dataclass(slots=True)
class Action:
    """Structured output from the soul engine."""

    type: ActionType = "direct_reply"
    content: Any = ""
    inner_thoughts: str = ""
    raw_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
