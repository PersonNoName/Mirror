"""Tool registry contracts."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


class ToolRegistry:
    """In-memory tool registry shared by the runtime."""

    def __init__(self) -> None:
        self._tools: dict[str, Any] = {}

    def register(self, name: str, tool: Any) -> None:
        """Register or replace a tool implementation by name."""

        self._tools[name] = tool

    def get(self, name: str) -> Any:
        """Return a registered tool, raising KeyError if missing."""

        return self._tools[name]

    def list_tools(self) -> list[str]:
        """Return registered tool names in stable sorted order."""

        return sorted(self._tools)

    def items(self) -> Iterable[tuple[str, Any]]:
        """Iterate over registered tool pairs."""

        return self._tools.items()


tool_registry = ToolRegistry()

