from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class CircuitBreakerState(BaseModel):
    name: str
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: Optional[datetime] = None
    state: Literal["closed", "open", "half_open"] = "closed"
    opened_at: Optional[datetime] = None
    half_open_probe_count: int = 0


class SnapshotRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    block_type: str
    version: int
    content: dict
    reason: Optional[str] = None
