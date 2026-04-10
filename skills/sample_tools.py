"""Local skill callables used by Phase 7 loader validation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


async def get_current_time_tool(params: dict[str, Any], context: Any | None = None) -> dict[str, str]:
    """Return the current UTC time; params are ignored in V1."""

    del params, context
    return {"time": datetime.now(timezone.utc).isoformat()}
