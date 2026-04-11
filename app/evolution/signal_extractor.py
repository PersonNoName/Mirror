"""Rule-based signal extraction for session adaptation and durable preference capture."""

from __future__ import annotations

import re
from typing import Any

from app.evolution.event_bus import Event, EventType, InteractionSignal
from app.tasks.models import Lesson


class SignalExtractor:
    """Extract lightweight interaction signals without LLM calls."""

    _ZH_CONCISE = "\u7b80\u6d01\u4e00\u70b9"
    _ZH_SHORT = "\u7b80\u77ed"
    _ZH_LESS = "\u5c11\u70b9"
    _ZH_NOT_TOO_LONG = "\u522b\u592a\u957f"
    _ZH_CHINESE = "\u4e2d\u6587"
    _ZH_SPEAK_CHINESE = "\u8bf4\u4e2d\u6587"
    _ZH_USE_CHINESE = "\u8bf7\u7528\u4e2d\u6587"
    _ZH_LESS_POLITE = "\u5c11\u70b9\u5ba2\u5957"
    _ZH_MORE_DIRECT = "\u76f4\u63a5\u4e00\u70b9"
    _ZH_NOT_TOO_POLITE = "\u4e0d\u8981\u592a\u5ba2\u6c14"
    _ZH_LISTEN_FIRST = "\u5148\u542c\u6211\u8bf4"
    _ZH_NO_ADVICE_1 = "\u4e0d\u8981\u6025\u7740\u7ed9\u5efa\u8bae"
    _ZH_NO_ADVICE_2 = "\u522b\u6025\u7740\u7ed9\u5efa\u8bae"
    _ZH_CHAT_WITH_ME = "\u5148\u966a\u6211\u804a\u804a"
    _ZH_TELL_ME_DIRECTLY = "\u76f4\u63a5\u544a\u8bc9\u6211\u600e\u4e48\u505a"
    _ZH_GIVE_ME_STEPS = "\u7ed9\u6211\u6b65\u9aa4"
    _ZH_HELP_ME_SOLVE = "\u5e2e\u6211\u89e3\u51b3"
    _ZH_WHAT_SHOULD_I_DO = "\u544a\u8bc9\u6211\u8be5\u600e\u4e48\u505a"

    _OBJECT_ALIASES = {
        "py": "Python",
        "python": "Python",
        "pyhton": "Python",
        "js": "JavaScript",
        "javascript": "JavaScript",
        "ts": "TypeScript",
        "typescript": "TypeScript",
        "vsc": "VSCode",
        "vs code": "VSCode",
        "vscode": "VSCode",
    }
    _RELATION_VERBS = {
        "likes": "likes",
        "dislikes": "dislikes",
        "prefers": "prefers",
        "uses": "uses",
    }
    _ENGLISH_PREFERENCE_PATTERNS = (
        (re.compile(r"\bi\s+(?:really\s+|still\s+|just\s+)?like\s+(?P<object>.+)$", re.I), "likes"),
        (re.compile(r"\bi\s+(?:really\s+)?love\s+(?P<object>.+)$", re.I), "likes"),
        (re.compile(r"\bi\s+(?:really\s+)?enjoy\s+(?P<object>.+)$", re.I), "likes"),
        (re.compile(r"\bi\s+(?:really\s+)?dislike\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"\bi\s+(?:really\s+)?hate\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"\bi\s+do\s+not\s+like\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"\bi\s+don't\s+like\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"\bi\s+(?:much\s+)?prefer\s+(?P<object>.+)$", re.I), "prefers"),
        (re.compile(r"\bi\s+(?:mostly\s+|usually\s+|often\s+)?use\s+(?P<object>.+)$", re.I), "uses"),
        (re.compile(r"\bi\s+(?:mostly\s+|usually\s+|often\s+)?code\s+in\s+(?P<object>.+)$", re.I), "uses"),
        (re.compile(r"\bi\s+(?:mostly\s+|usually\s+|often\s+)?work\s+with\s+(?P<object>.+)$", re.I), "uses"),
    )
    _CHINESE_PREFERENCE_PATTERNS = (
        (re.compile(r"^我(?:真的|其实)?(?:很|更)?不喜欢(?P<object>.+)$"), "dislikes"),
        (re.compile(r"^我(?:真的|其实)?讨厌(?P<object>.+)$"), "dislikes"),
        (re.compile(r"^我(?:真的|其实)?(?:更)?偏好(?P<object>.+)$"), "prefers"),
        (re.compile(r"^我(?:真的|其实)?(?:更|很)?喜欢(?P<object>.+)$"), "likes"),
        (re.compile(r"^我(?:平时|一般|通常|经常|主要)?(?:都)?(?:用|使用)(?P<object>.+)$"), "uses"),
        (re.compile(r"^我(?:平时|一般|通常|经常|主要)?(?:都)?用(?P<object>.+)写代码$"), "uses"),
    )

    def __init__(self, personality_evolver: Any, event_bus: Any | None = None) -> None:
        self.personality_evolver = personality_evolver
        self.event_bus = event_bus

    async def handle_dialogue_ended(self, event: Event) -> None:
        text = f"{event.payload.get('text', '')}\n{event.payload.get('reply', '')}".lower()
        signal = self._extract_signal(event, text)
        if signal is not None:
            await self.personality_evolver.fast_adapt(signal)
        lessons = [
            self._extract_explicit_preference_lesson(event),
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
        if any(
            token in text
            for token in (
                self._ZH_CONCISE,
                self._ZH_SHORT,
                self._ZH_LESS,
                self._ZH_NOT_TOO_LONG,
                "concise",
                "shorter",
            )
        ):
            signal_type = "prefer_concise"
            content = "本次对话使用更简洁的回复"
        elif any(
            token in text
            for token in (
                self._ZH_CHINESE,
                self._ZH_SPEAK_CHINESE,
                self._ZH_USE_CHINESE,
                "chinese",
            )
        ):
            signal_type = "language_zh"
            content = "本次对话使用中文回复"
        elif any(
            token in text
            for token in (
                self._ZH_LESS_POLITE,
                self._ZH_MORE_DIRECT,
                self._ZH_NOT_TOO_POLITE,
            )
        ):
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

    @classmethod
    def _extract_explicit_preference_lesson(cls, event: Event) -> Lesson | None:
        text = str(event.payload.get("text", "")).strip()
        candidate = cls._explicit_preference_candidate(text)
        if candidate is None:
            return None
        summary = candidate["summary"]
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="explicit_preference",
            outcome="observed",
            category="dialogue_explicit_preference",
            summary=summary,
            lesson_text=summary,
            details={
                "source": "dialogue_signal",
                "session_id": event.payload.get("session_id", ""),
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "preference_relation": candidate["relation"],
                "preference_object": candidate["object"],
                "source_utterance": text,
            },
            confidence=0.96,
        )

    @classmethod
    def _explicit_preference_candidate(cls, text: str) -> dict[str, str] | None:
        stripped = text.strip()
        if not stripped:
            return None
        for pattern, relation in cls._CHINESE_PREFERENCE_PATTERNS:
            match = pattern.search(stripped)
            if match is None:
                continue
            normalized = cls._normalize_preference_object(match.group("object"))
            if normalized is None:
                return None
            return cls._preference_candidate(relation, normalized)
        for pattern, relation in cls._ENGLISH_PREFERENCE_PATTERNS:
            match = pattern.search(stripped)
            if match is None:
                continue
            normalized = cls._normalize_preference_object(match.group("object"))
            if normalized is None:
                return None
            return cls._preference_candidate(relation, normalized)
        return None

    @classmethod
    def _preference_candidate(cls, relation: str, object_value: str) -> dict[str, str]:
        verb = cls._RELATION_VERBS[relation]
        return {
            "relation": relation,
            "object": object_value,
            "summary": f"User {verb} {object_value}.",
        }

    @classmethod
    def _normalize_preference_object(cls, raw_value: str) -> str | None:
        value = raw_value.strip().strip("。！？!?,，；;:”“\"'`()[]{}")
        value = re.split(
            r"(?:，|,|。|！|!|？|\?|；|;|\s+because\s+|\s+but\s+)",
            value,
            maxsplit=1,
        )[0].strip()
        value = re.sub(r"^(the|a|an)\s+", "", value, flags=re.I)
        value = re.sub(r"^(用|使用|做|写)\s*", "", value)
        collapsed = re.sub(r"\s+", " ", value)
        if not collapsed or len(collapsed) > 48:
            return None
        if collapsed.lower() in {"it", "this", "that", "them", "这个", "那个", "这些", "那些"}:
            return None
        return cls._OBJECT_ALIASES.get(collapsed.lower(), collapsed)

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

    @classmethod
    def _explicit_support_preference(cls, text: str) -> str:
        listening_tokens = (
            "just listen",
            "listen first",
            "don't give advice",
            "do not give advice",
            cls._ZH_LISTEN_FIRST,
            cls._ZH_NO_ADVICE_1,
            cls._ZH_NO_ADVICE_2,
            cls._ZH_CHAT_WITH_ME,
        )
        problem_tokens = (
            "help me solve",
            "tell me what to do",
            "give me steps",
            "what should i do",
            cls._ZH_TELL_ME_DIRECTLY,
            cls._ZH_GIVE_ME_STEPS,
            cls._ZH_HELP_ME_SOLVE,
            cls._ZH_WHAT_SHOULD_I_DO,
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
