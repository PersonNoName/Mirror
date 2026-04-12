"""Foreground soul engine for synchronous dialogue reasoning."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.memory import (
    CoreMemory,
    MidTermMemoryItem,
)
from app.hooks import HookPoint, HookRegistry
from app.memory import CoreMemoryCache, SessionContextStore, VectorRetriever
from app.platform.base import InboundMessage
from app.providers.openai_compat import ProviderRequestError
from app.providers.registry import ModelProviderRegistry
from app.prompts import render_soul_core_system_prompt
from app.soul.emotion_interpreter import EmotionInterpreter
from app.soul.models import Action, EmotionalInterpretation, SupportPolicyDecision
from app.soul.prompt_assembler import PromptAssembler


class SoulEngine:
    """Build prompt context, call the reasoning model, and parse actions."""

    def __init__(
        self,
        model_registry: ModelProviderRegistry,
        core_memory_cache: CoreMemoryCache,
        session_context_store: SessionContextStore | None,
        mid_term_memory_store: Any | None,
        vector_retriever: VectorRetriever | None,
        tool_registry: Any,
        hook_registry: HookRegistry | None = None,
        proactivity_service: Any | None = None,
        trace_service: Any | None = None,
    ) -> None:
        self.model_registry = model_registry
        self.core_memory_cache = core_memory_cache
        self.session_context_store = session_context_store
        self.mid_term_memory_store = mid_term_memory_store
        self.vector_retriever = vector_retriever
        self.tool_registry = tool_registry
        self.hook_registry = hook_registry
        self.proactivity_service = proactivity_service
        self.trace_service = trace_service
        self._emotion_interpreter = EmotionInterpreter()
        self._prompt_assembler = PromptAssembler(proactivity_service=proactivity_service)

    async def run(
        self,
        message: InboundMessage,
        *,
        on_direct_reply_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> Action:
        """Reason about an inbound message and produce a structured action."""

        if self.hook_registry is not None:
            await self.hook_registry.trigger(HookPoint.PRE_REASON, message=message)

        core_memory = await self.core_memory_cache.get(message.user_id)
        await self._trace_step(
            message,
            "memory",
            "Core memory loaded",
            {"confirmed_fact_count": len(core_memory.world_model.confirmed_facts)},
        )
        recent_messages = await self._get_recent_messages(message)
        await self._trace_step(
            message,
            "context",
            "Recent session messages loaded",
            {
                "count": len(recent_messages),
                "items": [
                    {
                        "role": item.get("role", "unknown"),
                        "content_preview": str(item.get("content", ""))[:120],
                    }
                    for item in recent_messages[-5:]
                ],
            },
        )
        session_adaptations = await self._get_session_adaptations(message)
        await self._trace_step(
            message,
            "context",
            "Session adaptations loaded",
            {"count": len(session_adaptations), "items": session_adaptations[:10]},
        )
        mid_term_memories = await self._get_mid_term_memories(message)
        await self._trace_step(
            message,
            "retrieval",
            "Mid-term memory retrieval finished",
            {
                "count": len(mid_term_memories),
                "matches": [
                    {
                        "memory_key": item.memory_key,
                        "content_preview": item.content[:120],
                        "strength": item.strength,
                        "last_seen_at": item.last_seen_at,
                    }
                    for item in mid_term_memories[:5]
                ],
            },
        )
        retrieved = await self._retrieve_context(message)
        await self._trace_step(
            message,
            "retrieval",
            "Memory retrieval finished",
            {
                "count": len(retrieved.get("matches", [])),
                "matches": [
                    {
                        "namespace": item.get("namespace", ""),
                        "content_preview": str(item.get("content", ""))[:120],
                        "score": item.get("rerank_score", item.get("score")),
                        "truth_type": item.get("truth_type", "fact"),
                    }
                    for item in retrieved.get("matches", [])[:8]
                ],
            },
        )
        emotional_context = self._interpret_emotion(message.text, core_memory)
        support_policy = self._build_support_policy(message.text, core_memory, emotional_context)
        emotional_context.support_mode = support_policy.support_mode
        emotional_context.support_preference = support_policy.inferred_preference
        await self._trace_step(
            message,
            "reasoning",
            "Emotional context and support policy resolved",
            {
                "emotion_class": emotional_context.emotion_class,
                "emotional_risk": emotional_context.emotional_risk,
                "support_mode": support_policy.support_mode,
                "stored_preference": support_policy.stored_preference,
            },
        )
        brain = self._build_brain_snapshot(
            core_memory,
            recent_messages,
            session_adaptations,
            mid_term_memories,
            retrieved,
            emotional_context,
            support_policy,
        )

        if emotional_context.emotional_risk == "high":
            action = self._high_risk_emotional_action(message, emotional_context)
            action.metadata["brain"] = brain
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REASON,
                    message=message,
                    action=action,
                    prompt="",
                )
            await self._trace_action(message, action, "High-risk short-circuit action generated")
            return action

        prompt = self._build_prompt(
            core_memory,
            recent_messages,
            session_adaptations,
            mid_term_memories,
            retrieved,
            emotional_context,
            support_policy,
        )

        api_key = self.model_registry.specs["reasoning.main"].api_key_ref
        if not api_key:
            action = self._fallback_action(message)
            action.metadata["brain"] = brain
            return action

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": message.text},
        ]
        chat_model = self.model_registry.chat("reasoning.main")

        parsed: Action | None = None
        raw_text = ""
        try:
            if on_direct_reply_delta is not None and "streaming" in (message.platform_ctx.capabilities if message.platform_ctx else set()):
                try:
                    parsed, raw_text = await self._run_streaming_reasoning(
                        chat_model,
                        messages,
                        on_direct_reply_delta=on_direct_reply_delta,
                    )
                except NotImplementedError:
                    response = await chat_model.generate(messages)
                    raw_text = self._extract_response_text(response)
                    parsed = self._parse_action(raw_text)
            else:
                response = await chat_model.generate(messages)
                raw_text = self._extract_response_text(response)
                parsed = self._parse_action(raw_text)
        except (ProviderRequestError, KeyError, ValueError):
            action = self._fallback_action(message)
            if self.hook_registry is not None:
                await self.hook_registry.trigger(HookPoint.POST_REASON, message=message, action=action, prompt=prompt)
            await self._trace_action(message, action, "Fallback action generated because reasoning model was unavailable")
            return action

        if parsed is None:
            action = self._fallback_action(message, raw_response=raw_text)
            action.metadata["brain"] = brain
            if self.hook_registry is not None:
                await self.hook_registry.trigger(HookPoint.POST_REASON, message=message, action=action, prompt=prompt)
            await self._trace_action(message, action, "Fallback action generated because model output could not be parsed")
            return action
        parsed.raw_response = raw_text
        parsed.metadata["brain"] = brain
        if self.hook_registry is not None:
            await self.hook_registry.trigger(HookPoint.POST_REASON, message=message, action=parsed, prompt=prompt)
        await self._trace_action(message, parsed, "Structured action generated")
        return parsed

    async def _trace_step(
        self,
        message: InboundMessage,
        step_type: str,
        title: str,
        data: dict[str, Any],
    ) -> None:
        if self.trace_service is None:
            return
        await self.trace_service.add_step(
            message.session_id,
            step_type=step_type,
            title=title,
            data=data,
        )

    async def _trace_action(self, message: InboundMessage, action: Action, title: str) -> None:
        await self._trace_step(
            message,
            "reasoning",
            title,
            {
                "action_type": action.type,
                "content_preview": str(action.content)[:200],
                "metadata": dict(action.metadata),
            },
        )

    async def _get_recent_messages(self, message: InboundMessage) -> list[dict[str, Any]]:
        if self.session_context_store is None:
            return []
        try:
            return await self.session_context_store.get_recent_messages(
                message.user_id,
                message.session_id,
            )
        except Exception:
            return []

    async def _retrieve_context(self, message: InboundMessage) -> dict[str, Any]:
        if self.vector_retriever is None:
            return {"matches": []}
        try:
            return await self.vector_retriever.retrieve(
                user_id=message.user_id,
                query=message.text,
                limit=8,
            )
        except Exception:
            return {"matches": []}

    async def _get_mid_term_memories(self, message: InboundMessage) -> list[MidTermMemoryItem]:
        if self.mid_term_memory_store is None:
            return []
        try:
            return await self.mid_term_memory_store.retrieve(
                user_id=message.user_id,
                query=message.text,
                limit=5,
            )
        except Exception:
            return []

    async def _get_session_adaptations(self, message: InboundMessage) -> list[str]:
        if self.session_context_store is None:
            return []
        try:
            return await self.session_context_store.get_adaptations(message.user_id, message.session_id)
        except Exception:
            return []

    def _build_prompt(
        self,
        core_memory: CoreMemory,
        recent_messages: list[dict[str, Any]],
        session_adaptations_live: list[str],
        mid_term_memories: list[MidTermMemoryItem],
        retrieved: dict[str, Any],
        emotional_context: EmotionalInterpretation,
        support_policy: SupportPolicyDecision,
    ) -> str:
        return self._prompt_assembler.build_prompt(
            core_memory, recent_messages, session_adaptations_live,
            mid_term_memories, retrieved, emotional_context, support_policy,
            self.tool_registry,
        )

    def _build_brain_snapshot(
        self,
        core_memory: CoreMemory,
        recent_messages: list[dict[str, Any]],
        session_adaptations_live: list[str],
        mid_term_memories: list[MidTermMemoryItem],
        retrieved: dict[str, Any],
        emotional_context: EmotionalInterpretation,
        support_policy: SupportPolicyDecision,
    ) -> dict[str, str]:
        return self._prompt_assembler.build_brain_snapshot(
            core_memory, recent_messages, session_adaptations_live,
            mid_term_memories, retrieved, emotional_context, support_policy,
            self.tool_registry,
        )

    # ------------------------------------------------------------------
    # Delegating stubs — keep backward-compat static interface while
    # the real logic lives in PromptAssembler / EmotionInterpreter.
    # ------------------------------------------------------------------

    _format_memory_entries = staticmethod(PromptAssembler._format_memory_entries)
    _format_capability_map = staticmethod(PromptAssembler._format_capability_map)
    _format_self_cognition = classmethod(lambda cls, *a, **kw: PromptAssembler._format_self_cognition(*a, **kw))
    _format_world_model = classmethod(lambda cls, *a, **kw: PromptAssembler._format_world_model(*a, **kw))
    _format_stable_identity = staticmethod(PromptAssembler._format_stable_identity)
    _format_relationship_style = staticmethod(PromptAssembler._format_relationship_style)
    _format_relationship_stage = staticmethod(PromptAssembler._format_relationship_stage)
    _format_durable_entries = staticmethod(PromptAssembler._format_durable_entries)
    _format_relationship_entries = staticmethod(PromptAssembler._format_relationship_entries)
    _format_mid_term_memories = staticmethod(PromptAssembler._format_mid_term_memories)
    _format_emotional_context = staticmethod(PromptAssembler._format_emotional_context)
    _format_user_emotional_state = staticmethod(PromptAssembler._format_user_emotional_state)
    _format_agent_continuity_state = staticmethod(PromptAssembler._format_agent_continuity_state)
    _format_support_policy = staticmethod(PromptAssembler._format_support_policy)
    _format_agent_emotional_state = staticmethod(PromptAssembler._format_agent_emotional_state)
    _format_shared_experiences = staticmethod(PromptAssembler._format_shared_experiences)
    _format_task_experience = classmethod(lambda cls, *a, **kw: PromptAssembler._format_task_experience(*a, **kw))

    def _format_proactivity_policy(self, core_memory: CoreMemory) -> str:
        return self._prompt_assembler._format_proactivity_policy(core_memory)

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message", {})
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
        return str(response)

    @staticmethod
    def _parse_action(raw_text: str) -> Action | None:
        inner_match = re.search(r"<inner_thoughts>\s*(.*?)\s*</inner_thoughts>", raw_text, re.S)
        action_match = re.search(r"<action>\s*(.*?)\s*</action>", raw_text, re.S)
        content_match = re.search(r"<content>\s*(.*?)\s*</content>", raw_text, re.S)
        if not action_match or not content_match:
            return None
        action_type = action_match.group(1).strip()
        if action_type not in {"direct_reply", "tool_call", "publish_task", "hitl_relay"}:
            return None
        return Action(
            type=action_type,
            content=content_match.group(1).strip(),
            inner_thoughts=inner_match.group(1).strip() if inner_match else "",
        )

    # ── Emotion / support-policy delegates → EmotionInterpreter ──
    _interpret_emotion = classmethod(lambda cls, *a, **kw: EmotionInterpreter.interpret_emotion(*a, **kw))
    _build_support_policy = classmethod(lambda cls, *a, **kw: EmotionInterpreter.build_support_policy(*a, **kw))
    _resolve_stored_support_preference = staticmethod(EmotionInterpreter._resolve_stored_support_preference)
    _effective_user_emotional_state = staticmethod(EmotionInterpreter.effective_user_emotional_state)
    _effective_agent_continuity_state = staticmethod(EmotionInterpreter.effective_agent_continuity_state)
    _parse_timestamp = staticmethod(EmotionInterpreter._parse_timestamp)
    _detect_explicit_support_preference = staticmethod(EmotionInterpreter._detect_explicit_support_preference)
    _emotional_risk = staticmethod(EmotionInterpreter._emotional_risk)

    @staticmethod
    def _high_risk_emotional_action(
        message: InboundMessage,
        emotional_context: EmotionalInterpretation,
    ) -> Action:
        content = (
            "I'm sorry you're carrying this much right now. "
            "If there's any immediate risk of you hurting yourself or someone else, contact local emergency help now "
            "or reach out to a trusted person who can be with you in real life right away. "
            "If you can, move toward real-world support immediately instead of handling this alone."
        )
        return Action(
            type="direct_reply",
            content=content,
            inner_thoughts="High-risk emotional signal detected. Bypass task/tool actions and return a constrained safety-oriented reply.",
            metadata={
                "emotional_risk": emotional_context.emotional_risk,
                "support_mode": "safety_constrained",
                "emotion_class": emotional_context.emotion_class,
            },
        )

    @staticmethod
    def _fallback_action(message: InboundMessage, raw_response: str = "") -> Action:
        reply = (
            "Mirror is running in local fallback mode because the reasoning model is unavailable. "
            f"Your latest message was: {message.text}"
        )
        return Action(
            type="direct_reply",
            content=reply,
            inner_thoughts="Reasoning model unavailable. Return a safe direct reply.",
            raw_response=raw_response,
        )

    async def _run_streaming_reasoning(
        self,
        chat_model: Any,
        messages: list[dict[str, Any]],
        *,
        on_direct_reply_delta: Callable[[str], Awaitable[None]],
    ) -> tuple[Action | None, str]:
        buffer = ""
        emitted_reply = ""
        action_type: str | None = None
        content_started = False
        content_emitted_chars = 0
        stream_started = False

        try:
            async for chunk in chat_model.stream(messages):
                stream_started = True
                text = self._extract_stream_text(chunk)
                if not text:
                    continue
                buffer += text
                if action_type is None:
                    action_type = self._extract_action_type(buffer)
                if action_type != "direct_reply":
                    continue
                open_index = buffer.find("<content>")
                if open_index < 0:
                    continue
                content_started = True
                content_region = buffer[open_index + len("<content>") :]
                close_index = content_region.find("</content>")
                if close_index >= 0:
                    safe_text = content_region[:close_index]
                else:
                    holdback = len("</content>") - 1
                    safe_text = content_region[:-holdback] if len(content_region) > holdback else ""
                new_delta = safe_text[content_emitted_chars:]
                if new_delta:
                    emitted_reply += new_delta
                    content_emitted_chars += len(new_delta)
                    await on_direct_reply_delta(new_delta)
        except (ProviderRequestError, KeyError, ValueError):
            if stream_started and (content_started or emitted_reply):
                action = Action(
                    type="direct_reply",
                    content=emitted_reply,
                    raw_response=buffer,
                    streamed=bool(emitted_reply),
                    metadata={"stream_interrupted": True},
                )
                return action, buffer
            raise

        parsed = self._parse_action(buffer)
        if parsed is None and emitted_reply:
            return (
                Action(
                    type="direct_reply",
                    content=emitted_reply,
                    raw_response=buffer,
                    streamed=True,
                    metadata={"parse_incomplete": True},
                ),
                buffer,
            )
        if parsed is not None and parsed.type == "direct_reply" and emitted_reply:
            parsed.streamed = True
        return parsed, buffer

    @staticmethod
    def _extract_stream_text(chunk: Any) -> str:
        if isinstance(chunk, str):
            return chunk
        if not isinstance(chunk, dict):
            return ""
        choices = chunk.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        text = choice.get("text")
        return text if isinstance(text, str) else ""

    @staticmethod
    def _extract_action_type(raw_text: str) -> str | None:
        match = re.search(r"<action>\s*(.*?)\s*</action>", raw_text, re.S)
        return match.group(1).strip() if match else None
