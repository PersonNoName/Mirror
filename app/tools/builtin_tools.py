"""Built-in runtime tools registered during bootstrap."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.tools.registry import ToolRegistry


def register_builtin_tools(tool_registry: ToolRegistry) -> list[str]:
    """Register built-in tools used as extension baselines."""

    @tool_registry.register(
        name="get_current_time",
        description="Return the current UTC time in ISO-8601 format.",
        schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        source="builtin",
    )
    async def get_current_time(params: dict[str, Any], context: Any | None = None) -> dict[str, str]:
        del params, context
        return {"time": datetime.now(timezone.utc).isoformat()}

    return ["get_current_time"]
