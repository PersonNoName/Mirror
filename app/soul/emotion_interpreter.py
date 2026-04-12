"""Emotion interpretation and support-policy resolution extracted from SoulEngine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.memory import (
    AgentContinuityState,
    CoreMemory,
    UserEmotionalState,
)
from app.memory.emotion_constants import (
    detect_emotion_class,
    detect_emotional_risk,
    detect_duration_hint,
    detect_intensity,
    text_has_topic_overlap,
)
from app.soul.models import EmotionalInterpretation, SupportPolicyDecision


class EmotionInterpreter:
    """Stateless helper that interprets user emotion and decides support policy."""

    @classmethod
    def interpret_emotion(cls, text: str, core_memory: CoreMemory) -> EmotionalInterpretation:
        normalized = text.lower()
        support_preference = cls._resolve_stored_support_preference(core_memory)

        emotion_class = detect_emotion_class(normalized)
        intensity = detect_intensity(normalized, emotion_class)
        duration_hint = detect_duration_hint(normalized)
        emotional_risk = detect_emotional_risk(normalized)

        carryover = cls.effective_user_emotional_state(core_memory.user_emotional_state)
        if carryover is not None:
            current_is_emotional = emotion_class != "neutral"
            topic_related = text_has_topic_overlap(
                normalized, carryover.unresolved_topics
            )
            should_inherit = current_is_emotional or topic_related

            if should_inherit:
                if emotion_class == "neutral" and carryover.emotion_class != "neutral":
                    emotion_class = carryover.emotion_class
                if intensity == "low" and carryover.intensity in {"medium", "high"}:
                    intensity = carryover.intensity
                if duration_hint == "unknown":
                    duration_hint = "carryover"
                if emotional_risk == "low" and carryover.emotional_risk in {"medium", "high"}:
                    emotional_risk = carryover.emotional_risk

            if support_preference == "unknown" and carryover.support_preference != "unknown":
                support_preference = carryover.support_preference

        return EmotionalInterpretation(
            emotion_class=emotion_class,
            intensity=intensity,
            duration_hint=duration_hint,
            support_preference=support_preference,
            support_mode="safety_constrained" if emotional_risk in {"medium", "high"} else "blended",
            emotional_risk=emotional_risk,
        )

    @classmethod
    def build_support_policy(
        cls,
        text: str,
        core_memory: CoreMemory,
        emotional_context: EmotionalInterpretation,
    ) -> SupportPolicyDecision:
        normalized = text.lower()
        carryover = cls.effective_user_emotional_state(core_memory.user_emotional_state)
        stored_preference = cls._resolve_stored_support_preference(core_memory)
        explicit_preference = cls._detect_explicit_support_preference(normalized)
        carryover_mode = carryover.support_mode if carryover is not None else "blended"

        if emotional_context.emotional_risk in {"medium", "high"}:
            return SupportPolicyDecision(
                support_mode="safety_constrained",
                inferred_preference=explicit_preference if explicit_preference != "unknown" else stored_preference,
                stored_preference=stored_preference,
                rationale="Emotional risk elevated; keep the response supportive, bounded, and safety-aware.",
            )
        if explicit_preference == "listening":
            return SupportPolicyDecision(
                support_mode="listening",
                inferred_preference="listening",
                stored_preference=stored_preference,
                rationale="The user explicitly asked for listening-first support.",
            )
        if explicit_preference == "problem_solving":
            return SupportPolicyDecision(
                support_mode="problem_solving",
                inferred_preference="problem_solving",
                stored_preference=stored_preference,
                rationale="The user explicitly asked for actionable help.",
            )
        if stored_preference == "listening":
            return SupportPolicyDecision(
                support_mode="listening",
                inferred_preference="listening",
                stored_preference=stored_preference,
                rationale="Stored support preference suggests listening-first support unless the user asks otherwise.",
            )
        if stored_preference == "problem_solving":
            return SupportPolicyDecision(
                support_mode="problem_solving",
                inferred_preference="problem_solving",
                stored_preference=stored_preference,
                rationale="Stored support preference suggests concise actionable help unless the user asks otherwise.",
            )
        if (
            carryover is not None
            and carryover_mode in {"listening", "problem_solving"}
            and emotional_context.emotion_class in {"sadness", "anxiety", "loneliness", "overwhelm", carryover.emotion_class}
        ):
            return SupportPolicyDecision(
                support_mode=carryover_mode,
                inferred_preference=(
                    carryover.support_preference
                    if carryover.support_preference != "unknown"
                    else stored_preference
                ),
                stored_preference=stored_preference,
                rationale="Recent cross-session emotional carryover suggests preserving the prior support style unless the user redirects.",
            )
        if emotional_context.emotion_class in {"sadness", "anxiety", "loneliness", "overwhelm"}:
            return SupportPolicyDecision(
                support_mode="listening",
                inferred_preference="unknown",
                stored_preference=stored_preference,
                rationale="The message is emotionally loaded and does not explicitly request solutions.",
            )
        return SupportPolicyDecision(
            support_mode="blended",
            inferred_preference="unknown",
            stored_preference=stored_preference,
            rationale="No strong support preference signal; acknowledge first, then keep suggestions light.",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_stored_support_preference(core_memory: CoreMemory) -> str:
        carryover = EmotionInterpreter.effective_user_emotional_state(core_memory.user_emotional_state)
        if carryover is not None and carryover.support_preference in {"listening", "problem_solving", "mixed"}:
            return carryover.support_preference
        for entry in core_memory.world_model.confirmed_facts + core_memory.world_model.inferred_memories:
            if not str(getattr(entry, "memory_key", "")).startswith("support_preference:"):
                continue
            _, _, preference = str(entry.memory_key).partition(":")
            if preference in {"listening", "problem_solving", "mixed"}:
                return preference
        return "unknown"

    @staticmethod
    def effective_user_emotional_state(
        state: UserEmotionalState,
    ) -> UserEmotionalState | None:
        if not state.carryover_until and not state.last_observed_at:
            return None
        now = datetime.now(timezone.utc)
        carryover_until = EmotionInterpreter._parse_timestamp(state.carryover_until)
        if carryover_until is not None and carryover_until < now:
            return None
        if carryover_until is None:
            last_observed_at = EmotionInterpreter._parse_timestamp(state.last_observed_at)
            if last_observed_at is None or now - last_observed_at > timedelta(days=7):
                return None
        return state

    @staticmethod
    def effective_agent_continuity_state(
        state: AgentContinuityState,
    ) -> AgentContinuityState | None:
        if (
            not state.last_event_at
            and not state.active_signals
            and not state.last_shift_reason
            and not state.continuity_summary
        ):
            return None
        now = datetime.now(timezone.utc)
        reference = EmotionInterpreter._parse_timestamp(state.last_event_at) or EmotionInterpreter._parse_timestamp(state.updated_at)
        if reference is None:
            return None
        elapsed = now - reference
        if elapsed > timedelta(days=7):
            return None
        if elapsed > timedelta(days=3):
            from copy import copy
            decayed = copy(state)
            if decayed.caution_level == "high":
                decayed.caution_level = "medium"
            elif decayed.caution_level == "medium":
                decayed.caution_level = "low"
            decayed.repair_mode = False
            decayed.relational_confidence = min(
                0.7, decayed.relational_confidence + 0.1
            )
            return decayed
        return state

    @staticmethod
    def _detect_explicit_support_preference(text: str) -> str:
        listening_tokens = (
            "just listen",
            "listen first",
            "don't give advice",
            "do not give advice",
            "先听我说",
            "别急着给建议",
            "不要急着给建议",
            "先陪我聊聊",
        )
        problem_tokens = (
            "help me solve",
            "tell me what to do",
            "give me steps",
            "what should i do",
            "直接告诉我怎么做",
            "给我步骤",
            "帮我解决",
            "告诉我该怎么做",
        )
        if any(token in text for token in listening_tokens):
            return "listening"
        if any(token in text for token in problem_tokens):
            return "problem_solving"
        return "unknown"

    @staticmethod
    def _parse_timestamp(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _emotional_risk(text: str) -> str:
        return detect_emotional_risk(text)
