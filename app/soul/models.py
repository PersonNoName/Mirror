"""Foreground reasoning action models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ActionType = Literal["direct_reply", "tool_call", "publish_task", "hitl_relay"]
EmotionClass = Literal[
    "neutral",
    "sadness",
    "anxiety",
    "frustration",
    "anger",
    "overwhelm",
    "loneliness",
    "relief",
    "joy",
]
EmotionIntensity = Literal["low", "medium", "high"]
DurationHint = Literal["momentary", "recent", "ongoing", "unknown"]
SupportPreference = Literal["listening", "problem_solving", "mixed", "unknown"]
SupportMode = Literal["listening", "problem_solving", "blended", "safety_constrained"]
EmotionalRisk = Literal["low", "medium", "high"]


@dataclass(slots=True)
class Action:
    """Structured output from the soul engine."""

    type: ActionType = "direct_reply"
    content: Any = ""
    inner_thoughts: str = ""
    raw_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EmotionalInterpretation:
    """Structured emotional reading for the current turn."""

    emotion_class: EmotionClass = "neutral"
    intensity: EmotionIntensity = "low"
    duration_hint: DurationHint = "unknown"
    support_preference: SupportPreference = "unknown"
    support_mode: SupportMode = "blended"
    emotional_risk: EmotionalRisk = "low"


@dataclass(slots=True)
class SupportPolicyDecision:
    """Foreground support policy derived from current intent and stored preference."""

    support_mode: SupportMode = "blended"
    inferred_preference: SupportPreference = "unknown"
    stored_preference: SupportPreference = "unknown"
    rationale: str = ""
