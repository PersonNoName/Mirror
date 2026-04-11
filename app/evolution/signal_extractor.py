"""Rule-based signal extraction for session adaptation."""

from __future__ import annotations

from typing import Any

from app.evolution.event_bus import Event, EventType, InteractionSignal
from app.tasks.models import Lesson


class SignalExtractor:
    """Extract lightweight interaction signals without LLM calls."""

    def __init__(self, personality_evolver: Any, event_bus: Any | None = None) -> None:
        self.personality_evolver = personality_evolver
        self.event_bus = event_bus

    async def handle_dialogue_ended(self, event: Event) -> None:
        text = f"{event.payload.get('text', '')}\n{event.payload.get('reply', '')}".lower()
        signal = self._extract_signal(event, text)
        if signal is not None:
            await self.personality_evolver.fast_adapt(signal)
        lessons = [
            self._extract_support_preference_lesson(event),
            self._extract_proactivity_preference_lesson(event),
        ]
        if self.event_bus is not None:
            for lesson in lessons:
                if lesson is None:
                    continue
                await self.event_bus.emit(
                    Event(
                        type=EventType.LESSON_GENERATED,
                        payload={"lesson": self._lesson_payload(lesson)},
                    )
                )

    def _extract_signal(self, event: Event, text: str) -> InteractionSignal | None:
        content = None
        signal_type = None
        if any(token in text for token in ("简洁一点", "简短", "少点", "别太长", "concise", "shorter")):
            signal_type = "prefer_concise"
            content = "本次对话使用更简洁的回复"
        elif any(token in text for token in ("中文", "说中文", "请用中文", "chinese")):
            signal_type = "language_zh"
            content = "本次对话使用中文回复"
        elif any(token in text for token in ("少点客套", "直接一点", "不要太客气")):
            signal_type = "tone_direct"
            content = "本次对话保持直接、少客套"
        if signal_type is None:
            return None
        return InteractionSignal(
            signal_type=signal_type,
            user_id=event.payload.get("user_id", ""),
            session_id=event.payload.get("session_id", ""),
            content=content or "",
            confidence=0.9,
            source_event_id=event.id,
            metadata={"source": EventType.DIALOGUE_ENDED},
        )

    @staticmethod
    def _extract_support_preference_lesson(event: Event) -> Lesson | None:
        text = str(event.payload.get("text", "")).lower()
        preference = SignalExtractor._explicit_support_preference(text)
        if preference == "unknown":
            return None
        if preference == "listening":
            summary = "User prefers listening-first support when emotionally loaded."
        else:
            summary = "User prefers actionable problem-solving support."
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="support_preference",
            outcome="observed",
            category="dialogue_support_preference",
            summary=summary,
            lesson_text=summary,
            details={
                "source": "dialogue_signal",
                "session_id": event.payload.get("session_id", ""),
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "support_preference": preference,
            },
            confidence=0.95,
        )

    @staticmethod
    def _explicit_support_preference(text: str) -> str:
        listening_tokens = (
            "just listen",
            "listen first",
            "don't give advice",
            "do not give advice",
            "先听我说",
            "不要急着给建议",
            "别急着给建议",
        )
        problem_tokens = (
            "help me solve",
            "tell me what to do",
            "give me steps",
            "what should i do",
            "直接告诉我怎么做",
            "给我步骤",
            "帮我解决",
        )
        if any(token in text for token in listening_tokens):
            return "listening"
        if any(token in text for token in problem_tokens):
            return "problem_solving"
        return "unknown"

    @staticmethod
    def _extract_proactivity_preference_lesson(event: Event) -> Lesson | None:
        text = str(event.payload.get("text", "")).lower()
        preference = SignalExtractor._explicit_proactivity_preference(text)
        if preference == "unknown":
            return None
        summary = (
            "User explicitly allows gentle follow-up on important topics."
            if preference == "allow"
            else "User explicitly does not want proactive follow-up or reminders."
        )
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="proactivity_preference",
            outcome="observed",
            category="dialogue_proactivity_preference",
            summary=summary,
            lesson_text=summary,
            details={
                "source": "dialogue_signal",
                "session_id": event.payload.get("session_id", ""),
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "proactivity_preference": preference,
            },
            confidence=0.95,
        )

    @staticmethod
    def _explicit_proactivity_preference(text: str) -> str:
        allow_tokens = (
            "check in later",
            "follow up later",
            "feel free to check in",
            "ask me about it later",
            "you can remind me later",
        )
        suppress_tokens = (
            "don't remind me",
            "do not remind me",
            "don't follow up",
            "do not follow up",
            "don't check in",
            "no reminders",
        )
        if any(token in text for token in suppress_tokens):
            return "suppress"
        if any(token in text for token in allow_tokens):
            return "allow"
        return "unknown"

    @staticmethod
    def _lesson_payload(lesson: Lesson) -> dict[str, Any]:
        return {
            "id": lesson.id,
            "source_task_id": lesson.source_task_id,
            "user_id": lesson.user_id,
            "domain": lesson.domain,
            "outcome": lesson.outcome,
            "category": lesson.category,
            "summary": lesson.summary,
            "root_cause": lesson.root_cause,
            "lesson_text": lesson.lesson_text,
            "is_agent_capability_issue": lesson.is_agent_capability_issue,
            "subject": lesson.subject,
            "relation": lesson.relation,
            "object": lesson.object,
            "details": lesson.details,
            "confidence": lesson.confidence,
        }
