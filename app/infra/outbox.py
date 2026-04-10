"""Outbox data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


@dataclass(slots=True)
class OutboxEvent:
    """Application outbox record aligned with the Phase 0 schema."""

    id: str = field(default_factory=lambda: str(uuid4()))
    topic: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    retry_count: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    published_at: datetime | None = None

