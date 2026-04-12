"""Rule-based signal extraction for session adaptation and durable preference capture."""

from __future__ import annotations

import re
from typing import Any

from app.evolution.event_bus import Event, EventType, InteractionSignal
from app.evolution.helpers import extract_json
from app.memory.emotion_constants import (
    detect_emotion_class,
    detect_emotional_risk,
    detect_intensity,
    extract_unresolved_topics,
    is_resolution_signal,
    LISTENING_TOKENS,
    PROBLEM_SOLVING_TOKENS,
    VULNERABLE_EMOTION_CLASSES,
)
from app.providers.openai_compat import ProviderRequestError
from app.tasks.models import Lesson


class SignalExtractor:
    """Extract lightweight interaction signals without LLM calls."""

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
        (
            re.compile(
                r"^\s*i\s+(?:really\s+|still\s+|just\s+)?like\s+(?P<object>.+)$", re.I
            ),
            "likes",
        ),
        (re.compile(r"^\s*i\s+(?:really\s+)?love\s+(?P<object>.+)$", re.I), "likes"),
        (re.compile(r"^\s*i\s+(?:really\s+)?enjoy\s+(?P<object>.+)$", re.I), "likes"),
        (
            re.compile(r"^\s*i\s+(?:really\s+)?dislike\s+(?P<object>.+)$", re.I),
            "dislikes",
        ),
        (re.compile(r"^\s*i\s+(?:really\s+)?hate\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"^\s*i\s+do\s+not\s+like\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"^\s*i\s+don't\s+like\s+(?P<object>.+)$", re.I), "dislikes"),
        (re.compile(r"^\s*i\s+(?:much\s+)?prefer\s+(?P<object>.+)$", re.I), "prefers"),
        (
            re.compile(
                r"^\s*i\s+(?:mostly\s+|usually\s+|often\s+)?use\s+(?P<object>.+)$", re.I
            ),
            "uses",
        ),
        (
            re.compile(
                r"^\s*i\s+(?:mostly\s+|usually\s+|often\s+)?code\s+in\s+(?P<object>.+)$",
                re.I,
            ),
            "uses",
        ),
        (
            re.compile(
                r"^\s*i\s+(?:mostly\s+|usually\s+|often\s+)?work\s+with\s+(?P<object>.+)$",
                re.I,
            ),
            "uses",
        ),
    )
    _CHINESE_PREFERENCE_PATTERNS = (
        (
            re.compile(
                r"^\s*\u6211(?:\u771f\u7684|\u5176\u5b9e)?(?:\u5f88|\u66f4)?\u4e0d\u559c\u6b22(?P<object>.+)$"
            ),
            "dislikes",
        ),
        (
            re.compile(
                r"^\s*\u6211(?:\u771f\u7684|\u5176\u5b9e)?\u8ba8\u538c(?P<object>.+)$"
            ),
            "dislikes",
        ),
        (
            re.compile(
                r"^\s*\u6211(?:\u771f\u7684|\u5176\u5b9e)?(?:\u66f4)?\u504f\u597d(?P<object>.+)$"
            ),
            "prefers",
        ),
        (
            re.compile(
                r"^\s*\u6211(?:\u771f\u7684|\u5176\u5b9e)?(?:\u66f4|\u5f88)?\u559c\u6b22(?P<object>.+)$"
            ),
            "likes",
        ),
        (
            re.compile(
                r"^\s*\u6211(?:\u5e73\u65f6|\u4e00\u822c|\u901a\u5e38|\u7ecf\u5e38|\u4e3b\u8981)?(?:\u90fd)?(?:\u7528|\u4f7f\u7528)(?P<object>.+)$"
            ),
            "uses",
        ),
        (
            re.compile(
                r"^\s*\u6211(?:\u5e73\u65f6|\u4e00\u822c|\u901a\u5e38|\u7ecf\u5e38|\u4e3b\u8981)?(?:\u90fd)?\u7528(?P<object>.+)\u5199\u4ee3\u7801$"
            ),
            "uses",
        ),
    )
    _COPY_MARKERS = (
        "copied",
        "copy",
        "paste",
        "pasted",
        "quoted",
        "quote",
        "forwarded",
        "example",
        "sample",
        "log",
        "prompt",
        "\u590d\u5236",
        "\u7c98\u8d34",
        "\u8f6c\u53d1",
        "\u5f15\u7528",
        "\u539f\u6587",
        "\u793a\u4f8b",
        "\u4e0b\u9762\u8fd9\u6bb5",
        "\u8fd9\u6bb5\u8bdd",
        "\u8fd9\u53e5\u8bdd",
        "\u65e5\u5fd7",
        "summarize the following",
        "summarize this",
        "translate the following",
        "translate this",
        "rewrite the following",
        "rewrite this",
        "polish the following",
        "below text",
        "\u5e2e\u6211\u603b\u7ed3",
        "\u603b\u7ed3\u4e00\u4e0b",
        "\u603b\u7ed3\u4e0b\u9762",
        "\u5e2e\u6211\u7ffb\u8bd1",
        "\u7ffb\u8bd1\u4e00\u4e0b",
        "\u7ffb\u8bd1\u4e0b\u9762",
        "\u5e2e\u6211\u6da6\u8272",
        "\u6da6\u8272\u4e00\u4e0b",
        "\u6574\u7406\u4e00\u4e0b",
        "\u5e2e\u6211\u6574\u7406",
        "\u4e0b\u9762\u7684\u8bdd",
        "\u4e0b\u9762\u7684\u5185\u5bb9",
    )
    _QUOTE_SEGMENT_PATTERNS = (
        re.compile(r"[\u201c\"](?P<segment>.+?)[\u201d\"]"),
        re.compile(r"[\u2018'](?P<segment>.+?)[\u2019']"),
        re.compile(r"`(?P<segment>.+?)`"),
        re.compile(r"\u300c(?P<segment>.+?)\u300d"),
        re.compile(r"\u300e(?P<segment>.+?)\u300f"),
    )

    _REVIEWER_PROFILE = "lite.extraction"
    _REVIEWER_EVENT_KEY = "preference_review_lite_extraction"
    _IMPLICIT_EVENT_KEY = "implicit_preference_lite_extraction"

    def __init__(
        self,
        personality_evolver: Any,
        event_bus: Any | None = None,
        *,
        model_registry: Any | None = None,
        circuit_breaker: Any | None = None,
    ) -> None:
        self.personality_evolver = personality_evolver
        self.event_bus = event_bus
        self.model_registry = model_registry
        self.circuit_breaker = circuit_breaker

    async def handle_dialogue_ended(self, event: Event) -> None:
        text = (
            f"{event.payload.get('text', '')}\n{event.payload.get('reply', '')}".lower()
        )
        signal = self._extract_signal(event, text)
        if signal is not None:
            await self.personality_evolver.fast_adapt(signal)
        lessons = [
            await self._extract_explicit_preference_lesson(event),
            await self._extract_implicit_preference_lesson(event),
            self._extract_support_preference_lesson(event),
            self._extract_proactivity_preference_lesson(event),
            self._extract_emotional_continuity_lesson(event),
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

    @classmethod
    def _extract_signal(cls, event: Event, text: str) -> InteractionSignal | None:
        content = None
        signal_type = None
        if any(
            token in text
            for token in (
                "\u7b80\u6d01\u4e00\u70b9",
                "\u7b80\u77ed",
                "\u5c11\u70b9",
                "\u522b\u592a\u957f",
                "concise",
                "shorter",
            )
        ):
            signal_type = "prefer_concise"
            content = "\u672c\u6b21\u5bf9\u8bdd\u4f7f\u7528\u66f4\u7b80\u6d01\u7684\u56de\u590d"
        elif any(
            token in text
            for token in (
                "\u4e2d\u6587",
                "\u8bf4\u4e2d\u6587",
                "\u8bf7\u7528\u4e2d\u6587",
                "chinese",
            )
        ):
            signal_type = "language_zh"
            content = "\u672c\u6b21\u5bf9\u8bdd\u4f7f\u7528\u4e2d\u6587\u56de\u590d"
        elif any(
            token in text
            for token in (
                "\u5c11\u70b9\u5ba2\u5957",
                "\u76f4\u63a5\u4e00\u70b9",
                "\u4e0d\u8981\u592a\u5ba2\u6c14",
            )
        ):
            signal_type = "tone_direct"
            content = "\u672c\u6b21\u5bf9\u8bdd\u4fdd\u6301\u76f4\u63a5\u3001\u5c11\u5ba2\u5957"
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

    async def _extract_explicit_preference_lesson(self, event: Event) -> Lesson | None:
        text = str(event.payload.get("text", "")).strip()
        direct_candidate = self._explicit_preference_candidate(text)
        quoted_candidate = self._quoted_or_copied_preference_candidate(text)
        has_copy_markers = self._contains_copy_markers(text)

        if direct_candidate is None and quoted_candidate is None:
            return None
        if direct_candidate is not None and not has_copy_markers:
            return self._build_preference_lesson(
                event,
                candidate=direct_candidate,
                explicit_user_statement=True,
                explicit_user_confirmation=True,
                confidence=0.96,
                category="dialogue_explicit_preference",
            )

        candidate = direct_candidate or quoted_candidate
        if candidate is None:
            return None
        review = await self.review_preference_candidate(
            text=text,
            candidate=candidate,
            default_classification="quoted_or_forwarded"
            if quoted_candidate is not None
            else "self_reported",
        )
        return self._build_reviewed_preference_lesson(
            event, candidate=candidate, review=review
        )

    async def _extract_implicit_preference_lesson(self, event: Event) -> Lesson | None:
        text = str(event.payload.get("text", "")).strip()
        if not text:
            return None
        if self._explicit_preference_candidate(text) is not None:
            return None
        if self._quoted_or_copied_preference_candidate(text) is not None:
            return None
        extracted = await self._extract_implicit_preference_candidate(text)
        if extracted is None:
            return None
        relation = str(extracted.get("relation", "")).strip()
        object_value = self._normalize_preference_object(
            str(extracted.get("object", "")).strip()
        )
        strength = str(extracted.get("preference_strength", "")).strip().lower()
        durability = str(extracted.get("durability", "")).strip().lower()
        classification = str(extracted.get("classification", "")).strip().lower()
        confidence = float(extracted.get("confidence") or 0.0)
        if relation not in self._RELATION_VERBS or object_value is None:
            return None
        if strength not in {"implicit", "explicit"}:
            return None
        if durability not in {"stable", "situational", "unknown"}:
            durability = "unknown"
        if classification not in {"self_reported", "quoted_or_forwarded", "uncertain"}:
            return None
        candidate = self._preference_candidate(relation, object_value)
        summary = self._implicit_preference_summary(relation, object_value)
        requires_review = classification != "self_reported"
        memory_tier = (
            "session_hint" if durability == "situational" else "inference_candidate"
        )
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="implicit_preference",
            outcome="observed",
            category=(
                "dialogue_implicit_preference_review"
                if requires_review
                else "dialogue_implicit_preference"
            ),
            summary=summary,
            lesson_text=summary,
            details={
                "source": "dialogue_implicit_preference",
                "session_id": event.payload.get("session_id", ""),
                "explicit_user_statement": False,
                "explicit_user_confirmation": False,
                "preference_relation": candidate["relation"],
                "preference_object": candidate["object"],
                "source_utterance": text,
                "preference_strength": strength,
                "preference_durability": durability,
                "speaker_attribution": classification,
                "memory_tier": memory_tier,
                "evidence_type": "implicit_expression",
                "requires_review": requires_review,
                "review_reason": (
                    "quoted_or_copied_content"
                    if classification == "quoted_or_forwarded"
                    else (
                        "ambiguous_preference_evidence"
                        if classification == "uncertain"
                        else ""
                    )
                ),
                "review_source": "llm_inference",
                "review_confidence": confidence,
                "review_reasoning": str(extracted.get("reason", "")).strip(),
            },
            confidence=max(0.0, min(confidence, 0.74)),
        )

    @classmethod
    def _build_preference_lesson(
        cls,
        event: Event,
        *,
        candidate: dict[str, str],
        explicit_user_statement: bool,
        explicit_user_confirmation: bool,
        confidence: float,
        category: str,
        extra_details: dict[str, Any] | None = None,
    ) -> Lesson:
        details: dict[str, Any] = {
            "source": "dialogue_signal",
            "session_id": event.payload.get("session_id", ""),
            "explicit_user_statement": explicit_user_statement,
            "explicit_user_confirmation": explicit_user_confirmation,
            "preference_relation": candidate["relation"],
            "preference_object": candidate["object"],
            "source_utterance": str(event.payload.get("text", "")).strip(),
        }
        if extra_details:
            details.update(extra_details)
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="explicit_preference",
            outcome="observed",
            category=category,
            summary=candidate["summary"],
            lesson_text=candidate["summary"],
            details=details,
            confidence=confidence,
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
    def _quoted_or_copied_preference_candidate(cls, text: str) -> dict[str, str] | None:
        normalized = text.strip()
        lowered = normalized.lower()
        if not any(
            marker in lowered or marker in normalized for marker in cls._COPY_MARKERS
        ):
            return None
        segments: list[str] = []
        for pattern in cls._QUOTE_SEGMENT_PATTERNS:
            segments.extend(
                match.group("segment").strip() for match in pattern.finditer(normalized)
            )
        for separator in (":", "\uff1a", "-", "\u2014"):
            if separator in normalized:
                tail = normalized.split(separator, 1)[1].strip()
                if tail:
                    segments.append(tail)
        if "\n" in normalized:
            tail = normalized.split("\n", 1)[1].strip()
            if tail:
                segments.append(tail)
        for segment in segments:
            candidate = cls._explicit_preference_candidate(segment)
            if candidate is not None:
                return candidate
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
        value = raw_value.strip().strip(
            "\u3002\uff01\uff1f!?,\uff0c\uff1b;:\u201c\u201d\"'\u300c\u300d\u300e\u300f`()[]{}"
        )
        value = re.split(
            r"(?:\uff0c|,|\u3002|\uff01|!|\uff1f|\?|；|;|\s+because\s+|\s+but\s+)",
            value,
            maxsplit=1,
        )[0].strip()
        value = re.sub(r"^(the|a|an)\s+", "", value, flags=re.I)
        value = re.sub(r"^(\u7528|\u4f7f\u7528|\u505a|\u5199)\s*", "", value)
        collapsed = re.sub(r"\s+", " ", value)
        if not collapsed or len(collapsed) > 48:
            return None
        if collapsed.lower() in {
            "it",
            "this",
            "that",
            "them",
            "\u8fd9\u4e2a",
            "\u90a3\u4e2a",
            "\u8fd9\u4e9b",
            "\u90a3\u4e9b",
        }:
            return None
        return cls._OBJECT_ALIASES.get(collapsed.lower(), collapsed)

    async def _extract_implicit_preference_candidate(
        self, text: str
    ) -> dict[str, Any] | None:
        if self.model_registry is None:
            return None
        try:
            generate = self.model_registry.chat(self._REVIEWER_PROFILE).generate
            payload = [
                {
                    "role": "system",
                    "content": (
                        "Detect whether the user's message implies a personal preference worth tracking. "
                        "Return a JSON object with keys classification, preference_strength, durability, relation, object, confidence, and reason. "
                        "classification must be one of self_reported, quoted_or_forwarded, uncertain. "
                        "preference_strength must be one of explicit, implicit, weak, none. "
                        "durability must be one of stable, situational, unknown. "
                        "relation must be one of likes, dislikes, prefers, uses, none. "
                        "Only return a real object when there is a plausible user preference candidate; otherwise set preference_strength='none' and relation='none'."
                    ),
                },
                {"role": "user", "content": text},
            ]
            if self.circuit_breaker is None:
                response = await generate(payload)
            else:
                response = await self.circuit_breaker.call(
                    self._IMPLICIT_EVENT_KEY, generate, payload
                )
        except (ProviderRequestError, KeyError, NotImplementedError, ValueError):
            return None
        extracted = extract_json(response, {})
        if not isinstance(extracted, dict):
            return None
        return extracted

    @classmethod
    def _contains_copy_markers(cls, text: str) -> bool:
        lowered = text.lower()
        return any(marker in lowered or marker in text for marker in cls._COPY_MARKERS)

    @classmethod
    def _build_reviewed_preference_lesson(
        cls,
        event: Event,
        *,
        candidate: dict[str, str],
        review: dict[str, Any],
    ) -> Lesson:
        classification = str(review.get("classification", "uncertain")).strip().lower()
        review_confidence = float(review.get("confidence") or 0.58)
        if classification == "self_reported":
            return cls._build_preference_lesson(
                event,
                candidate=candidate,
                explicit_user_statement=True,
                explicit_user_confirmation=True,
                confidence=max(0.7, min(review_confidence, 0.96)),
                category="dialogue_explicit_preference",
                extra_details={
                    "review_source": review.get("source", "fallback"),
                    "review_classification": classification,
                    "review_confidence": review_confidence,
                    "review_reasoning": review.get("reason", ""),
                },
            )
        review_reason = (
            "quoted_or_copied_content"
            if classification == "quoted_or_forwarded"
            else "ambiguous_preference_evidence"
        )
        return cls._build_preference_lesson(
            event,
            candidate=candidate,
            explicit_user_statement=False,
            explicit_user_confirmation=False,
            confidence=min(review_confidence, 0.58),
            category="dialogue_explicit_preference_review",
            extra_details={
                "requires_review": True,
                "review_reason": review_reason,
                "review_source": review.get("source", "fallback"),
                "review_classification": classification,
                "review_confidence": review_confidence,
                "review_reasoning": review.get("reason", ""),
            },
        )

    async def review_preference_candidate(
        self,
        *,
        text: str,
        candidate: dict[str, str],
        default_classification: str,
    ) -> dict[str, Any]:
        fallback = self._fallback_review(
            text=text, candidate=candidate, classification=default_classification
        )
        if self.model_registry is None:
            return fallback
        try:
            generate = self.model_registry.chat(self._REVIEWER_PROFILE).generate
            payload = [
                {
                    "role": "system",
                    "content": (
                        "Classify whether the user's latest message is a true first-person preference statement "
                        "or quoted/copied content. Return JSON with keys classification, confidence, and reason. "
                        "classification must be one of self_reported, quoted_or_forwarded, uncertain. "
                        "Choose self_reported only when the message is best read as the user directly stating their own durable preference."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Message: {text}\n"
                        f"Extracted preference relation: {candidate['relation']}\n"
                        f"Extracted preference object: {candidate['object']}"
                    ),
                },
            ]
            if self.circuit_breaker is None:
                response = await generate(payload)
            else:
                response = await self.circuit_breaker.call(
                    self._REVIEWER_EVENT_KEY, generate, payload
                )
        except (ProviderRequestError, KeyError, NotImplementedError, ValueError):
            return fallback
        reviewed = extract_json(response, {})
        if not isinstance(reviewed, dict):
            return fallback
        classification = str(reviewed.get("classification", "")).strip().lower()
        if classification not in {"self_reported", "quoted_or_forwarded", "uncertain"}:
            return fallback
        try:
            confidence = float(reviewed.get("confidence", fallback["confidence"]))
        except (TypeError, ValueError):
            confidence = float(fallback["confidence"])
        return {
            "classification": classification,
            "confidence": max(0.0, min(confidence, 1.0)),
            "reason": str(reviewed.get("reason", "")).strip(),
            "source": "llm_reviewer",
        }

    @classmethod
    def _fallback_review(
        cls, *, text: str, candidate: dict[str, str], classification: str
    ) -> dict[str, Any]:
        if classification == "self_reported" and cls._contains_copy_markers(text):
            classification = "uncertain"
        confidence = 0.9 if classification == "self_reported" else 0.58
        return {
            "classification": classification,
            "confidence": confidence,
            "reason": f"heuristic_review_for_{candidate['relation']}_{candidate['object']}",
            "source": "rule_fallback",
        }

    @classmethod
    def _implicit_preference_summary(cls, relation: str, object_value: str) -> str:
        verb = {
            "likes": "may like",
            "dislikes": "may dislike",
            "prefers": "may prefer",
            "uses": "may often use",
        }.get(relation, f"may {relation}")
        return f"User {verb} {object_value}."

    @classmethod
    def _extract_support_preference_lesson(cls, event: Event) -> Lesson | None:
        text = str(event.payload.get("text", "")).lower()
        preference = cls._explicit_support_preference(text)
        if preference == "unknown":
            return None
        summary = (
            "User prefers listening-first support when emotionally loaded."
            if preference == "listening"
            else "User prefers actionable problem-solving support."
        )
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
            "\u5148\u542c\u6211\u8bf4",
            "\u4e0d\u8981\u6025\u7740\u7ed9\u5efa\u8bae",
            "\u522b\u6025\u7740\u7ed9\u5efa\u8bae",
            "\u5148\u966a\u6211\u804a\u804a",
        )
        problem_tokens = (
            "help me solve",
            "tell me what to do",
            "give me steps",
            "what should i do",
            "\u76f4\u63a5\u544a\u8bc9\u6211\u600e\u4e48\u505a",
            "\u7ed9\u6211\u6b65\u9aa4",
            "\u5e2e\u6211\u89e3\u51b3",
            "\u544a\u8bc9\u6211\u8be5\u600e\u4e48\u505a",
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

    @classmethod
    def _extract_emotional_continuity_lesson(cls, event: Event) -> Lesson | None:
        user_text = str(event.payload.get("text", "")).strip()
        reply_text = str(event.payload.get("reply", "")).strip()
        if not user_text and not reply_text:
            return None

        # Analyse user text first; fall back to analysing the AI reply
        # so that emotional context embedded in the assistant's response
        # (e.g. "I can tell you're feeling overwhelmed") is not lost.
        user_normalized = user_text.lower()
        reply_normalized = reply_text.lower()
        combined_normalized = f"{user_normalized} {reply_normalized}".strip()

        # Primary detection from user text
        emotion_class = detect_emotion_class(user_normalized)
        # If neutral from user text, try the AI reply as a secondary source
        if emotion_class == "neutral" and reply_normalized:
            emotion_class = detect_emotion_class(reply_normalized)

        intensity = detect_intensity(user_normalized, emotion_class)
        support_mode = cls._detect_emotional_support_mode(user_normalized, emotion_class)
        unresolved_topics = extract_unresolved_topics(combined_normalized)
        resolved = is_resolution_signal(user_normalized)

        if emotion_class == "neutral" and not resolved:
            return None
        if resolved:
            summary = "Recent emotional carryover appears resolved or significantly reduced."
            return Lesson(
                source_task_id=event.id,
                user_id=event.payload.get("user_id", ""),
                domain="emotional_continuity",
                outcome="observed",
                category="emotional_resolution",
                summary=summary,
                lesson_text=summary,
                details={
                    "source": "dialogue_signal",
                    "session_id": event.payload.get("session_id", ""),
                    "resolved": True,
                    "source_utterance": user_text,
                },
                confidence=0.84,
            )
        summary = (
            f"User shows recent {emotion_class} carryover"
            + (f" around {', '.join(unresolved_topics[:2])}" if unresolved_topics else "")
            + "."
        )
        return Lesson(
            source_task_id=event.id,
            user_id=event.payload.get("user_id", ""),
            domain="emotional_continuity",
            outcome="observed",
            category="emotional_carryover",
            summary=summary,
            lesson_text=summary,
            details={
                "source": "dialogue_signal",
                "session_id": event.payload.get("session_id", ""),
                "emotion_class": emotion_class,
                "intensity": intensity,
                "emotional_risk": detect_emotional_risk(user_normalized),
                "support_mode": support_mode,
                "support_preference": (
                    "listening" if support_mode == "listening" else "unknown"
                ),
                "stability": "fragile" if intensity in {"medium", "high"} else "recovering",
                "unresolved_topics": unresolved_topics,
                "source_utterance": user_text,
            },
            confidence=0.78 if intensity == "low" else 0.86,
        )

    @staticmethod
    def _detect_emotion_class(text: str) -> str:
        return detect_emotion_class(text)

    @staticmethod
    def _detect_intensity(text: str, emotion_class: str) -> str:
        return detect_intensity(text, emotion_class)

    @staticmethod
    def _detect_emotional_support_mode(text: str, emotion_class: str) -> str:
        if any(token in text for token in LISTENING_TOKENS):
            return "listening"
        if any(token in text for token in PROBLEM_SOLVING_TOKENS):
            return "problem_solving"
        if emotion_class in VULNERABLE_EMOTION_CLASSES:
            return "listening"
        return "blended"

    @staticmethod
    def _detect_emotional_risk(text: str) -> str:
        return detect_emotional_risk(text)

    @staticmethod
    def _is_resolution_signal(text: str) -> bool:
        return is_resolution_signal(text)

    @staticmethod
    def _extract_unresolved_topics(text: str) -> list[str]:
        return extract_unresolved_topics(text)

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
