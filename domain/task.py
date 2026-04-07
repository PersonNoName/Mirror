from enum import Enum
from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_task_id: Optional[str] = None
    children_task_ids: list[str] = Field(default_factory=list)
    created_by: str = "main_agent"
    assigned_to: str = ""
    intent: str = ""
    prompt_snapshot: str = ""
    status: Literal[
        "pending", "running", "done", "failed", "interrupted", "cancelled"
    ] = "pending"
    priority: int = 1
    depends_on: list[str] = Field(default_factory=list)
    result: Optional[dict] = None
    error_trace: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    last_heartbeat_at: datetime = Field(default_factory=datetime.utcnow)
    heartbeat_timeout: int = 30
    created_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = Field(default_factory=dict)


class TaskResult(BaseModel):
    task_id: str
    status: Literal["done", "failed", "interrupted"] = "done"
    result: Optional[dict] = None
    error_trace: Optional[str] = None
    summary: Optional[str] = None
    files_changed: list[str] = Field(default_factory=list)
