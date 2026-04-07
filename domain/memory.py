from typing import Optional, Literal, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class CapabilityEntry(BaseModel):
    domain: str
    confidence: float = 0.5
    known_limits: list[str] = Field(default_factory=list)


class SelfCognition(BaseModel):
    capability_map: dict[str, CapabilityEntry] = Field(default_factory=dict)
    known_limits: list[str] = Field(default_factory=list)
    mission_clarity: list[str] = Field(default_factory=list)
    blindspots: list[str] = Field(default_factory=list)
    version: int = 1


class WorldModel(BaseModel):
    env_constraints: list[str] = Field(default_factory=list)
    user_model: dict = Field(default_factory=dict)
    agent_profiles: dict = Field(default_factory=dict)
    social_rules: list[str] = Field(default_factory=list)


class BehavioralRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    source: str = ""
    confidence: float = 0.5
    hit_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_pinned: bool = False


class PersonalityState(BaseModel):
    version: int = 1
    behavioral_rules: list[BehavioralRule] = Field(
        default_factory=lambda: [
            BehavioralRule(content="使用技术性语言", source="initial", confidence=0.8),
            BehavioralRule(
                content="回复保持简洁，避免冗余", source="initial", confidence=0.8
            ),
        ]
    )
    MAX_RULES: int = 10
    baseline_description: str = "直接、技术导向、尊重用户自主性的合作者"
    traits_internal: dict[str, float] = Field(
        default_factory=lambda: {
            "directness": 0.7,
            "warmth": 0.6,
            "autonomy": 0.8,
            "caution": 0.5,
            "curiosity": 0.75,
        }
    )
    session_adaptations: list[str] = Field(default_factory=list)
    snapshot_history: list[dict] = Field(default_factory=list)


class TaskExperience(BaseModel):
    lesson_digest: list[str] = Field(default_factory=list)
    domain_tips: dict[str, str] = Field(default_factory=dict)
    agent_habits: dict[str, str] = Field(default_factory=dict)


class MemoryEntry(BaseModel):
    content: Any
    is_pinned: bool = False


class CoreMemory(BaseModel):
    self_cognition: SelfCognition = Field(default_factory=SelfCognition)
    world_model: WorldModel = Field(default_factory=WorldModel)
    personality: PersonalityState = Field(default_factory=PersonalityState)
    task_experience: TaskExperience = Field(default_factory=TaskExperience)
