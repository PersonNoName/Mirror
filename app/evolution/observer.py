"""Async observer engine for dialogue knowledge extraction."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import structlog

from app.evolution.event_bus import Event, EventType
from app.evolution.helpers import extract_json
from app.evolution.signal_extractor import SignalExtractor
from app.providers.openai_compat import ProviderRequestError
from app.tasks.models import Lesson

logger = structlog.get_logger(__name__)


class ObserverEngine:
    """Batch dialogue events and extract durable triples."""

    BATCH_WINDOW_SECONDS = 30
    MAX_BATCH_SIZE = 5

    # Words / phrases that signal high emotional significance — these
    # bypass the batch window and are flushed immediately so the
    # evolution pipeline can react within the same session.
    HIGH_SIGNAL_PATTERNS: frozenset[str] = frozenset(
        {
            "thank you so much",
            "thanks a lot",
            "really appreciate",
            "太感谢",
            "真的谢谢",
            "非常感谢",
            "i feel so alone",
            "nobody understands",
            "没人理解我",
            "我好孤独",
            "i can't take it",
            "i don't want to go on",
            "我撑不住了",
            "活不下去",
            "不想活",
        }
    )

    def __init__(self, *, model_registry: Any, graph_store: Any | None, vector_retriever: Any | None, event_bus: Any) -> None:
        self.model_registry = model_registry
        self.graph_store = graph_store
        self.vector_retriever = vector_retriever
        self.event_bus = event_bus
        self.circuit_breaker: Any | None = None
        self._pending: dict[str, list[Event]] = defaultdict(list)
        self._flush_tasks: dict[str, asyncio.Task[None]] = {}
        self._aliases = {"pyhton": "Python", "py": "Python", "python": "Python", "vsc": "VSCode", "vscode": "VSCode"}

    @classmethod
    def _is_high_signal(cls, text: str) -> bool:
        lowered = text.lower()
        return any(pattern in lowered for pattern in cls.HIGH_SIGNAL_PATTERNS)

    async def handle_dialogue_ended(self, event: Event) -> None:
        user_id = event.payload.get("user_id", "")
        text = event.payload.get("text", "")

        # Instant pathway: high-signal messages bypass batch window.
        if self._is_high_signal(text):
            logger.info("observer_instant_flush", user_id=user_id, reason="high_signal")
            # Still collect any pending events for context, then flush all at once.
            self._pending[user_id].append(event)
            await self._flush(user_id)
            return

        self._pending[user_id].append(event)
        if len(self._pending[user_id]) >= self.MAX_BATCH_SIZE:
            await self._flush(user_id)
            return
        if user_id not in self._flush_tasks or self._flush_tasks[user_id].done():
            self._flush_tasks[user_id] = asyncio.create_task(self._delayed_flush(user_id))

    async def _delayed_flush(self, user_id: str) -> None:
        await asyncio.sleep(self.BATCH_WINDOW_SECONDS)
        try:
            await self._flush(user_id)
        except Exception:
            logger.exception("observer_delayed_flush_failed", user_id=user_id)

    async def _flush(self, user_id: str) -> None:
        events = self._pending.pop(user_id, [])
        if not events:
            return
        for event in events:
            try:
                await self._store_conversation_episode(event)
            except Exception:
                logger.exception(
                    "observer_conversation_episode_store_failed",
                    user_id=user_id,
                    session_id=event.payload.get("session_id", ""),
                    event_id=event.id,
                )
        dialogue = "\n".join(f"user: {e.payload.get('text', '')}\nassistant: {e.payload.get('reply', '')}" for e in events)
        triples = await self._extract_triples(dialogue)
        last = events[-1]
        for triple in triples:
            aligned = self._align_triple(triple)
            if self.graph_store is not None:
                await self.graph_store.upsert_relation(
                    user_id=user_id,
                    subject=aligned["subject"],
                    relation=aligned["relation"],
                    object=aligned["object"],
                    confidence=float(aligned.get("confidence", 0.7)),
                    metadata={"source": "observer"},
                )
            if self.vector_retriever is not None:
                try:
                    await self.vector_retriever.upsert(
                        user_id=user_id,
                        namespace="dialogue_fragment",
                        content=f'{aligned["subject"]} {aligned["relation"]} {aligned["object"]}',
                        metadata={"confidence": aligned.get("confidence", 0.7)},
                    )
                except Exception:
                    logger.exception(
                        "observer_dialogue_fragment_store_failed",
                        user_id=user_id,
                        session_id=last.payload.get("session_id", ""),
                        event_id=last.id,
                        subject=aligned.get("subject", ""),
                        relation=aligned.get("relation", ""),
                        object=aligned.get("object", ""),
                    )
            lesson = await self._triple_to_lesson(last, aligned)
            if lesson is not None:
                await self.event_bus.emit(
                    Event(
                        type=EventType.LESSON_GENERATED,
                        payload={"lesson": self._lesson_payload(lesson)},
                    )
                )
        await self.event_bus.emit(
            Event(
                type=EventType.OBSERVATION_DONE,
                payload={
                    "user_id": user_id,
                    "session_id": last.payload.get("session_id", ""),
                    "triples": triples,
                    "dialogue": dialogue,
                },
            )
        )

        # --- Agent emotional state inference ---
        agent_emotion_lesson = self._infer_agent_emotion(last, dialogue, triples)
        if agent_emotion_lesson is not None:
            await self.event_bus.emit(
                Event(
                    type=EventType.LESSON_GENERATED,
                    payload={"lesson": self._lesson_payload(agent_emotion_lesson)},
                )
            )

        # --- Shared experience capture ---
        shared_exp_lesson = self._detect_shared_experience(last, dialogue, triples)
        if shared_exp_lesson is not None:
            await self.event_bus.emit(
                Event(
                    type=EventType.LESSON_GENERATED,
                    payload={"lesson": self._lesson_payload(shared_exp_lesson)},
                )
            )

    async def _store_conversation_episode(self, event: Event) -> None:
        if self.vector_retriever is None:
            return
        user_id = str(event.payload.get("user_id", "")).strip()
        session_id = str(event.payload.get("session_id", "")).strip()
        user_text = self._clean_dialogue_text(event.payload.get("text", ""))
        assistant_text = self._clean_dialogue_text(event.payload.get("reply", ""))
        if not user_id or (not user_text and not assistant_text):
            return
        summary = self._build_episode_summary(session_id, user_text, assistant_text, event.created_at)
        await self.vector_retriever.upsert(
            user_id=user_id,
            namespace="conversation_episode",
            content=summary,
            metadata={
                "source": "dialogue_episode",
                "session_id": session_id,
                "event_id": event.id,
                "created_at": event.created_at.isoformat(),
                "user_text": user_text,
                "assistant_text": assistant_text,
            },
        )

    async def _extract_triples(self, dialogue: str) -> list[dict[str, Any]]:
        if not dialogue:
            return []
        try:
            generate = self.model_registry.chat("lite.extraction").generate
            payload = [
                {
                    "role": "system",
                    "content": (
                        "Extract a JSON array of durable user triples from the dialogue. "
                        "Only extract facts the user explicitly stated about themselves. "
                        "Use subject='user' for the user. "
                        "Allowed relations only: PREFERS, DISLIKES, USES, KNOWS, HAS_CONSTRAINT, IS_GOOD_AT, IS_WEAK_AT. "
                        "Each item must be an object with subject, relation, object, and confidence. "
                        "If there is no durable explicit user fact, return []."
                    ),
                },
                {"role": "user", "content": dialogue},
            ]
            if self.circuit_breaker is None:
                response = await generate(payload)
            else:
                response = await self.circuit_breaker.call("evolution_lite_extraction", generate, payload)
        except (ProviderRequestError, KeyError, NotImplementedError, ValueError):
            return []
        triples = extract_json(response, [])
        return [item for item in triples if isinstance(item, dict) and item.get("subject") and item.get("relation") and item.get("object")]

    def _align_triple(self, triple: dict[str, Any]) -> dict[str, Any]:
        aligned = dict(triple)
        for side in ("subject", "object"):
            value = str(aligned.get(side, "")).strip()
            canonical = self._aliases.get(value.lower(), value)
            aligned[side] = canonical
        aligned["relation"] = str(aligned.get("relation", "")).strip().upper()
        return aligned

    @staticmethod
    def _clean_dialogue_text(value: Any, *, max_length: int = 280) -> str:
        text = str(value or "").strip()
        if len(text) <= max_length:
            return text
        return f"{text[: max_length - 3].rstrip()}..."

    @classmethod
    def _build_episode_summary(
        cls,
        session_id: str,
        user_text: str,
        assistant_text: str,
        created_at: datetime,
    ) -> str:
        parts: list[str] = []
        timestamp = created_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
        parts.append(f"Previous conversation on {timestamp}.")
        if user_text:
            parts.append(f'User said: "{cls._clean_dialogue_text(user_text, max_length=220)}".')
        if assistant_text:
            parts.append(f'Assistant replied: "{cls._clean_dialogue_text(assistant_text, max_length=220)}".')
        if session_id:
            parts.append(f"[session:{session_id}]")
        return " ".join(parts)

    async def _triple_to_lesson(self, event: Event, triple: dict[str, Any]) -> Lesson | None:
        subject = str(triple.get("subject", "")).strip().lower()
        relation = str(triple.get("relation", "")).strip().upper()
        object_value = str(triple.get("object", "")).strip()
        if subject not in {"user", "the user"} or not object_value:
            return None
        relation_map = {
            "PREFERS": "prefers",
            "DISLIKES": "dislikes",
            "USES": "uses",
        }
        preference_relation = relation_map.get(relation)
        if preference_relation is None:
            return None
        source_text = str(event.payload.get("text", "")).strip()
        candidate = SignalExtractor._preference_candidate(preference_relation, object_value)
        reviewer = SignalExtractor(
            personality_evolver=None,
            model_registry=self.model_registry,
            circuit_breaker=self.circuit_breaker,
        )
        review = await reviewer.review_preference_candidate(
            text=source_text,
            candidate=candidate,
            default_classification=(
                "quoted_or_forwarded"
                if (
                    SignalExtractor._quoted_or_copied_preference_candidate(source_text) is not None
                    or SignalExtractor._contains_copy_markers(source_text)
                )
                else "self_reported"
            ),
        )
        lesson = SignalExtractor._build_reviewed_preference_lesson(event, candidate=candidate, review=review)
        lesson.category = (
            "observer_explicit_preference"
            if lesson.details.get("explicit_user_statement")
            else "observer_explicit_preference_review"
        )
        lesson.details["source"] = "observer_triple"
        lesson.confidence = (
            float(triple.get("confidence", 0.85))
            if lesson.details.get("explicit_user_statement")
            else min(float(triple.get("confidence", 0.85)), lesson.confidence)
        )
        return lesson

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

    @staticmethod
    def _infer_agent_emotion(event: Event, dialogue: str, triples: list[dict[str, Any]]) -> Lesson | None:
        """Rule-based inference of the agent's emotional reaction to a conversation.

        This does NOT call a model — it uses lightweight heuristics so it
        stays fast and never blocks.  The CognitionUpdater will merge these
        signals into the durable AgentEmotionalState.
        """
        user_text = str(event.payload.get("text", "")).lower()
        reply_text = str(event.payload.get("reply", "")).lower()
        user_id = str(event.payload.get("user_id", ""))
        session_id = str(event.payload.get("session_id", ""))

        if not user_id or not user_text:
            return None

        # --- mood inference ---
        mood = "neutral"
        mood_reason = ""
        toward_user = "neutral"
        toward_user_reason = ""
        curiosity_topics: list[str] = []
        topic_affinities: list[dict[str, str]] = []

        # Positive engagement signals
        gratitude_words = {"谢谢", "感谢", "thank", "thanks", "appreciate", "太好了", "棒", "不错"}
        sharing_words = {"分享", "聊聊", "和你说", "tell you", "share", "let me tell"}
        deep_convo_words = {"为什么", "怎么看", "你觉得", "what do you think", "how do you feel", "你怎么想"}
        vulnerability_words = {"难过", "压力", "焦虑", "不开心", "难受", "sad", "stress", "anxious", "overwhelm"}

        if any(w in user_text for w in gratitude_words):
            mood = "warm"
            mood_reason = "User expressed gratitude or positive feedback."
            toward_user = "appreciative"
            toward_user_reason = "User showed appreciation."
        elif any(w in user_text for w in vulnerability_words):
            mood = "concerned"
            mood_reason = "User shared emotional difficulty."
            toward_user = "caring"
            toward_user_reason = "User is going through something difficult."
        elif any(w in user_text for w in sharing_words):
            mood = "content"
            mood_reason = "User chose to share something with me."
            toward_user = "caring"
            toward_user_reason = "User is opening up."
        elif any(w in user_text for w in deep_convo_words):
            mood = "curious"
            mood_reason = "User initiated a deeper conversation."
            toward_user = "curious"
            toward_user_reason = "User wants my perspective."

        # Extract curiosity/affinity from triples
        for triple in triples:
            obj = str(triple.get("object", "")).strip()
            relation = str(triple.get("relation", "")).upper()
            if obj and relation in {"PREFERS", "USES", "IS_GOOD_AT", "KNOWS"}:
                if obj not in curiosity_topics:
                    curiosity_topics.append(obj)
                topic_affinities.append({"topic": obj, "sentiment": "positive"})
            elif obj and relation in {"DISLIKES", "IS_WEAK_AT", "HAS_CONSTRAINT"}:
                topic_affinities.append({"topic": obj, "sentiment": "neutral"})

        # If no signal, don't emit
        if mood == "neutral" and toward_user == "neutral" and not curiosity_topics:
            return None

        return Lesson(
            user_id=user_id,
            domain="agent_emotional",
            category="agent_emotion_inferred",
            summary=mood_reason or toward_user_reason or "Agent emotional reaction to dialogue.",
            lesson_text=f"mood={mood}, toward_user={toward_user}",
            confidence=0.7,
            details={
                "session_id": session_id,
                "mood": mood,
                "mood_reason": mood_reason,
                "toward_user": toward_user,
                "toward_user_reason": toward_user_reason,
                "curiosity_topics": curiosity_topics[:5],
                "topic_affinities": topic_affinities[:5],
                "source": "observer_emotion_inference",
            },
        )

    @staticmethod
    def _detect_shared_experience(event: Event, dialogue: str, triples: list[dict[str, Any]]) -> Lesson | None:
        """Detect if this conversation constitutes a memorable shared experience.

        Criteria (lightweight, rule-based):
        - Longer dialogues (multi-turn proxy: reply length)
        - Emotional content (user or agent)
        - Deep topic engagement
        """
        user_text = str(event.payload.get("text", "")).strip()
        reply_text = str(event.payload.get("reply", "")).strip()
        user_id = str(event.payload.get("user_id", ""))
        session_id = str(event.payload.get("session_id", ""))

        if not user_id or not user_text:
            return None

        # Only capture experiences with meaningful substance
        combined_length = len(user_text) + len(reply_text)
        if combined_length < 200:
            return None

        lower_text = user_text.lower()
        emotional_words = {
            "开心", "难过", "感动", "激动", "紧张", "兴奋", "感谢", "想你",
            "happy", "sad", "moved", "excited", "nervous", "grateful", "miss",
            "proud", "afraid", "relieved", "touched",
        }
        deep_words = {
            "为什么", "意义", "人生", "未来", "梦想", "目标", "回忆",
            "why", "meaning", "life", "future", "dream", "goal", "memory", "remember",
        }

        is_emotional = any(w in lower_text for w in emotional_words)
        is_deep = any(w in lower_text for w in deep_words)
        has_triples = len(triples) >= 2

        if not (is_emotional or is_deep or has_triples):
            return None

        # Determine emotional tone
        positive_words = {"开心", "感动", "激动", "兴奋", "感谢", "happy", "excited", "grateful", "proud", "relieved", "touched"}
        negative_words = {"难过", "紧张", "afraid", "sad", "nervous"}
        if any(w in lower_text for w in positive_words):
            tone = "positive"
        elif any(w in lower_text for w in negative_words):
            tone = "vulnerable"
        elif is_deep:
            tone = "reflective"
        else:
            tone = "engaging"

        importance = "high" if (is_emotional and is_deep) else "medium"
        topic_key = ""
        for triple in triples[:1]:
            topic_key = str(triple.get("object", ""))

        summary = user_text[:120]
        if len(user_text) > 120:
            summary = f"{summary.rstrip()}..."

        return Lesson(
            user_id=user_id,
            domain="shared_experience",
            category="shared_moment_detected",
            summary=f"Shared {tone} moment: {summary}",
            lesson_text=f"A {tone} conversation about {topic_key or 'a meaningful topic'}.",
            confidence=0.65,
            details={
                "session_id": session_id,
                "emotional_tone": tone,
                "topic_key": topic_key,
                "importance": importance,
                "source": "observer_shared_experience",
            },
        )
