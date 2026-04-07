from typing import Optional, Literal
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class Event(BaseModel):
    type: str
    payload: dict
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class InteractionSignal(BaseModel):
    type: Literal[
        "explicit_instruction",
        "implicit_behavior",
    ] = "implicit_behavior"
    content: str = ""
    behavior_tag: Optional[
        Literal[
            "shorten_response",
            "language_switch",
            "repeated_correction",
            "style_preference",
            "topic_redirect",
        ]
    ] = None
    strength: float = 1.0
    session_id: str = ""
    turn_index: int = 0


class EvolutionEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    type: Literal[
        "fast_adaptation",
        "rule_promoted",
        "rule_decayed",
        "capability_updated",
        "world_model_updated",
        "baseline_shifted",
        "user_explicit",
    ] = "fast_adaptation"
    summary: str = ""
    detail: dict = Field(default_factory=dict)
    session_id: Optional[str] = None


class VectorEntry(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str
    namespace: str
    metadata: dict = Field(default_factory=dict)
    embedding: Optional[list[float]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_pinned: bool = False


class EvolutionLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    operation_type: str
    target_block: Optional[str] = None
    before_state: Optional[dict] = None
    after_state: Optional[dict] = None
    event_id: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None


class Lesson(BaseModel):
    task_id: str
    domain: str
    outcome: Literal["done", "failed", "interrupted"] = "failed"
    root_cause: str
    lesson_text: str
    is_agent_capability_issue: bool = False
    is_pattern: bool = False
    subject: Optional[str] = None
    relation: Optional[str] = None
    object: Optional[str] = None
    confidence: float = 0.5
