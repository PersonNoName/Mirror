"""Foreground soul engine for synchronous dialogue reasoning."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from app.memory import (
    AgentContinuityState,
    CapabilityEntry,
    CoreMemory,
    DurableMemory,
    MemoryEntry,
    MidTermMemoryItem,
    RelationshipMemory,
    TaskExperience,
    UserEmotionalState,
    WorldModel,
)
from app.memory.emotion_constants import (
    detect_emotion_class,
    detect_emotional_risk,
    detect_duration_hint,
    detect_intensity,
    text_has_topic_overlap,
    VULNERABLE_EMOTION_CLASSES,
)
from app.hooks import HookPoint, HookRegistry
from app.memory import CoreMemoryCache, SessionContextStore, VectorRetriever
from app.platform.base import InboundMessage
from app.providers.openai_compat import ProviderRequestError
from app.providers.registry import ModelProviderRegistry
from app.prompts import render_soul_core_system_prompt
from app.soul.models import Action, EmotionalInterpretation, SupportPolicyDecision


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
        tool_descriptions = self.tool_registry.describe_tools()
        tool_list = "\n".join(
            f"- {item['name']}: {item['description'] or 'No description'} | schema={item['schema']}"
            for item in tool_descriptions
        ) or "- No tools are currently registered."
        core_personality = core_memory.personality.core_personality
        behavioral_rules = "\n".join(
            f"- {rule.rule}" for rule in core_personality.behavioral_rules
        ) or "- No persistent behavioral rules."
        persisted_adaptations = list(core_memory.personality.session_adaptation.current_items)
        merged_adaptations = persisted_adaptations + [
            item for item in session_adaptations_live if item not in persisted_adaptations
        ]
        session_adaptations = "\n".join(
            f"- {item}" for item in merged_adaptations
        ) or "- No active session adaptations for this session."
        recent_dialogue = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in recent_messages[-5:]
        ) or "No recent dialogue."
        mid_term_context = self._format_mid_term_memories(mid_term_memories)
        retrieved_context = "\n".join(
            (
                f"- [{item.get('namespace', 'unknown')}|{item.get('truth_type', 'fact')}|"
                f"{item.get('status', 'active')}] {item.get('content', '')}"
            )
            for item in retrieved.get("matches", [])
        ) or "- No retrieved context."

        return "\n\n".join(
            [
                render_soul_core_system_prompt(
                    self_cognition=self._format_self_cognition(core_memory),
                    world_model=self._format_world_model(core_memory.world_model),
                    stable_identity=self._format_stable_identity(core_memory, behavioral_rules),
                    relationship_style=self._format_relationship_style(core_memory),
                    relationship_stage=self._format_relationship_stage(core_memory.world_model),
                    proactivity_policy=self._format_proactivity_policy(core_memory),
                    emotional_context=self._format_emotional_context(emotional_context),
                    user_emotional_state=self._format_user_emotional_state(
                        self._effective_user_emotional_state(core_memory.user_emotional_state)
                    ),
                    agent_continuity_state=self._format_agent_continuity_state(
                        self._effective_agent_continuity_state(core_memory.agent_continuity_state)
                    ),
                    support_policy=self._format_support_policy(support_policy),
                    session_adaptations=(
                        "These adaptations are temporary and only apply to the current session.\n"
                        f"{session_adaptations}"
                    ),
                    task_experience=self._format_task_experience(core_memory.task_experience),
                    tool_list=tool_list,
                ),
                f"## Session Raw Context\n{recent_dialogue}",
                (
                    "## Recent Cross-Session Context\n"
                    "These items may be stale. Prefer recent mentions over older ones.\n"
                    f"{mid_term_context}"
                ),
                f"## Retrieved Context\n{retrieved_context}",
            ]
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
        tool_descriptions = self.tool_registry.describe_tools()
        tool_list = "\n".join(
            f"- {item['name']}: {item['description'] or 'No description'} | schema={item['schema']}"
            for item in tool_descriptions
        ) or "- No tools are currently registered."
        core_personality = core_memory.personality.core_personality
        behavioral_rules = "\n".join(
            f"- {rule.rule}" for rule in core_personality.behavioral_rules
        ) or "- No persistent behavioral rules."
        persisted_adaptations = list(core_memory.personality.session_adaptation.current_items)
        merged_adaptations = persisted_adaptations + [
            item for item in session_adaptations_live if item not in persisted_adaptations
        ]
        session_adaptations = "\n".join(f"- {item}" for item in merged_adaptations) or "- No active session adaptations for this session."

        return {
            "self_cognition": self._format_self_cognition(core_memory),
            "world_model": self._format_world_model(core_memory.world_model),
            "stable_identity": self._format_stable_identity(core_memory, behavioral_rules),
            "relationship_style": self._format_relationship_style(core_memory),
            "relationship_stage": self._format_relationship_stage(core_memory.world_model),
            "proactivity_policy": self._format_proactivity_policy(core_memory),
            "emotional_context": self._format_emotional_context(emotional_context),
            "user_emotional_state": self._format_user_emotional_state(
                self._effective_user_emotional_state(core_memory.user_emotional_state)
            ),
            "agent_continuity_state": self._format_agent_continuity_state(
                self._effective_agent_continuity_state(core_memory.agent_continuity_state)
            ),
            "support_policy": self._format_support_policy(support_policy),
            "session_adaptations": (
                "These adaptations are temporary and only apply to the current session.\n"
                f"{session_adaptations}"
            ),
            "task_experience": self._format_task_experience(core_memory.task_experience),
            "tool_list": tool_list,
        }

    @staticmethod
    def _format_memory_entries(entries: list[MemoryEntry], empty_text: str) -> str:
        lines = [f"- {entry.content}" for entry in entries if str(entry.content).strip()]
        return "\n".join(lines) or f"- {empty_text}"

    @staticmethod
    def _format_capability_map(capability_map: dict[str, CapabilityEntry]) -> str:
        if not capability_map:
            return "- No explicit capabilities recorded."
        lines: list[str] = []
        for name, entry in capability_map.items():
            description = entry.description.strip() or name
            details: list[str] = [description]
            if entry.confidence > 0:
                details.append(f"confidence={entry.confidence:.2f}")
            if entry.limitations:
                details.append(f"limitations={', '.join(item for item in entry.limitations if item)}")
            lines.append(f"- {name}: {' | '.join(details)}")
        return "\n".join(lines)

    @classmethod
    def _format_self_cognition(cls, core_memory: CoreMemory) -> str:
        self_cognition = core_memory.self_cognition
        return "\n".join(
            [
                "Capabilities:",
                cls._format_capability_map(self_cognition.capability_map),
                "Known Limits:",
                cls._format_memory_entries(self_cognition.known_limits, "No known limits recorded."),
                "Mission Clarity:",
                cls._format_memory_entries(self_cognition.mission_clarity, "No mission guidance recorded."),
                "Blindspots:",
                cls._format_memory_entries(self_cognition.blindspots, "No blindspots recorded."),
            ]
        )

    @classmethod
    def _format_world_model(cls, world_model: WorldModel) -> str:
        confirmed_facts = cls._format_durable_entries(
            world_model.confirmed_facts,
            "No confirmed facts recorded.",
        )
        inferred_memories = cls._format_durable_entries(
            world_model.inferred_memories,
            "No inferred memories recorded.",
        )
        relationship_history = cls._format_relationship_entries(
            world_model.relationship_history,
            "No relationship history recorded.",
        )
        pending_confirmations = cls._format_durable_entries(
            world_model.pending_confirmations,
            "No pending confirmations.",
        )
        memory_conflicts = cls._format_durable_entries(
            world_model.memory_conflicts,
            "No memory conflicts recorded.",
        )
        return "\n".join(
            [
                "Confirmed Facts:",
                confirmed_facts,
                "Inferred Memory:",
                inferred_memories,
                "Relationship History:",
                relationship_history,
                "Pending Confirmation:",
                pending_confirmations,
                "Memory Conflicts:",
                memory_conflicts,
            ]
        )

    @staticmethod
    def _format_stable_identity(core_memory: CoreMemory, behavioral_rules: str) -> str:
        core_personality = core_memory.personality.core_personality
        baseline = core_personality.baseline_description or "Calm, direct, collaborative."
        version = core_personality.version
        updated_at = core_personality.updated_at or "unknown"
        return "\n".join(
            [
                f"Baseline: {baseline}",
                f"Version: {version}",
                f"Updated At: {updated_at}",
                "Behavioral Rules:",
                behavioral_rules,
            ]
        )

    @staticmethod
    def _format_relationship_style(core_memory: CoreMemory) -> str:
        style = core_memory.personality.relationship_style
        return "\n".join(
            [
                f"- warmth={style.warmth:.2f}",
                f"- boundary_strength={style.boundary_strength:.2f}",
                f"- supportiveness={style.supportiveness:.2f}",
                f"- humor={style.humor:.2f}",
                f"- preferred_closeness={style.preferred_closeness}",
            ]
        )

    @staticmethod
    def _format_relationship_stage(world_model: WorldModel) -> str:
        stage = world_model.relationship_stage
        behavior_hint = {
            "unfamiliar": "Use stronger boundaries and cite memory conservatively.",
            "trust_building": "Use light familiarity and confirm memory carefully.",
            "stable_companion": "Use continuity naturally, but keep commitments bounded.",
            "vulnerable_support": "Prioritize support and conservative suggestions without expanding promises.",
            "repair_and_recovery": "Reduce assertive memory claims and avoid overfamiliar phrasing.",
        }.get(stage.stage, "Use stronger boundaries and cite memory conservatively.")
        shared_events = (
            "\n".join(f"- {item}" for item in stage.recent_shared_events[:3])
            if stage.recent_shared_events
            else "- No recent shared events recorded."
        )
        return "\n".join(
            [
                f"- stage={stage.stage}",
                f"- confidence={stage.confidence:.2f}",
                f"- supports_vulnerability={str(stage.supports_vulnerability).lower()}",
                f"- repair_needed={str(stage.repair_needed).lower()}",
                f"- recent_transition_reason={stage.recent_transition_reason or 'No recent transition recorded.'}",
                f"- behavior_hint={behavior_hint}",
                "Recent Shared Events:",
                shared_events,
            ]
        )

    def _format_proactivity_policy(self, core_memory: CoreMemory) -> str:
        if self.proactivity_service is not None:
            snapshot = self.proactivity_service.prompt_policy_snapshot(core_memory)
            return "\n".join(
                [
                    f"- enabled={str(snapshot.get('enabled', True)).lower()}",
                    f"- stored_preference={snapshot.get('stored_preference', 'unknown')}",
                    f"- pending_followup_count={snapshot.get('pending_followup_count', 0)}",
                    f"- last_proactive_at={snapshot.get('last_proactive_at', 'never')}",
                    f"- last_suppression_reason={snapshot.get('last_suppression_reason', 'none')}",
                    f"- policy_hint={snapshot.get('policy_hint', 'Only follow up when context is important and bounded.')}",
                ]
            )
        stored_preference = "unknown"
        for entry in core_memory.world_model.confirmed_facts + core_memory.world_model.inferred_memories:
            key = str(getattr(entry, "memory_key", ""))
            if not key.startswith("proactivity_preference:"):
                continue
            _, _, preference = key.partition(":")
            if preference in {"allow", "suppress"}:
                stored_preference = preference
                break
        return "\n".join(
            [
                "- enabled=true",
                f"- stored_preference={stored_preference}",
                "- pending_followup_count=0",
                "- last_proactive_at=never",
                "- last_suppression_reason=none",
                "- policy_hint=Only follow up when context is important and bounded.",
            ]
        )

    @staticmethod
    def _format_durable_entries(entries: list[DurableMemory], empty_text: str) -> str:
        lines = []
        for entry in entries:
            content = str(entry.content).strip()
            if not content:
                continue
            status = "confirmed" if entry.confirmed_by_user else entry.status
            if str(entry.memory_key).startswith("support_preference:"):
                lines.append(
                    f"- [support_preference|{entry.truth_type}|{status}|confidence={entry.confidence:.2f}|source={entry.source}] {content}"
                )
            elif str(entry.memory_key).startswith("proactivity_preference:"):
                lines.append(
                    f"- [proactivity_preference|{entry.truth_type}|{status}|confidence={entry.confidence:.2f}|source={entry.source}] {content}"
                )
            else:
                lines.append(
                    f"- [{entry.truth_type}|{status}|confidence={entry.confidence:.2f}|source={entry.source}] {content}"
                )
        return "\n".join(lines) or f"- {empty_text}"

    @staticmethod
    def _format_relationship_entries(entries: list[RelationshipMemory], empty_text: str) -> str:
        lines = []
        for entry in entries:
            relation_text = f"{entry.subject} {entry.relation} {entry.object}".strip()
            content = relation_text if relation_text else str(entry.content).strip()
            if not content:
                continue
            status = "confirmed" if entry.confirmed_by_user else entry.status
            lines.append(
                f"- [relationship|{status}|confidence={entry.confidence:.2f}|source={entry.source}] {content}"
            )
        return "\n".join(lines) or f"- {empty_text}"

    @staticmethod
    def _format_mid_term_memories(entries: list[MidTermMemoryItem]) -> str:
        lines = []
        for entry in entries:
            content = str(entry.content).strip()
            if not content:
                continue
            lines.append(
                f"- [{entry.memory_type}|strength={entry.strength:.2f}|mentions={entry.mention_count}|last_seen={entry.last_seen_at}] {content}"
            )
        return "\n".join(lines) or "- No recent cross-session context."

    @staticmethod
    def _format_emotional_context(emotional_context: EmotionalInterpretation) -> str:
        return "\n".join(
            [
                f"- emotion_class={emotional_context.emotion_class}",
                f"- intensity={emotional_context.intensity}",
                f"- duration_hint={emotional_context.duration_hint}",
                f"- support_preference={emotional_context.support_preference}",
                f"- support_mode={emotional_context.support_mode}",
                f"- emotional_risk={emotional_context.emotional_risk}",
            ]
        )

    @staticmethod
    def _format_user_emotional_state(state: UserEmotionalState | None) -> str:
        if state is None:
            return "\n".join(
                [
                    "- active=false",
                    "- carryover=none",
                    "- support_mode=blended",
                    "- support_preference=unknown",
                    "- unresolved_topics=none",
                    "- state_hint=No active cross-session emotional carryover.",
                ]
            )
        unresolved_topics = ", ".join(item for item in state.unresolved_topics if item) or "none"
        return "\n".join(
            [
                "- active=true",
                f"- emotion_class={state.emotion_class}",
                f"- intensity={state.intensity}",
                f"- emotional_risk={state.emotional_risk}",
                f"- support_mode={state.support_mode}",
                f"- support_preference={state.support_preference}",
                f"- stability={state.stability}",
                f"- unresolved_topics={unresolved_topics}",
                f"- last_observed_at={state.last_observed_at or 'unknown'}",
                f"- carryover_until={state.carryover_until or 'unknown'}",
                f"- carryover_summary={state.carryover_summary or 'No emotional summary recorded.'}",
            ]
        )

    @staticmethod
    def _format_agent_continuity_state(state: AgentContinuityState | None) -> str:
        if state is None:
            return "\n".join(
                [
                    "- active=false",
                    "- caution_level=low",
                    "- warmth_level=medium",
                    "- repair_mode=false",
                    "- recovery_mode=false",
                    "- relational_confidence=0.50",
                    "- continuity_hint=No active cross-session agent continuity shift.",
                ]
            )
        active_signals = ", ".join(item for item in state.active_signals if item) or "none"
        return "\n".join(
            [
                "- active=true",
                f"- caution_level={state.caution_level}",
                f"- warmth_level={state.warmth_level}",
                f"- repair_mode={str(state.repair_mode).lower()}",
                f"- recovery_mode={str(state.recovery_mode).lower()}",
                f"- relational_confidence={state.relational_confidence:.2f}",
                f"- active_signals={active_signals}",
                f"- last_event_at={state.last_event_at or 'unknown'}",
                f"- last_shift_reason={state.last_shift_reason or 'No recent shift recorded.'}",
                f"- continuity_summary={state.continuity_summary or 'No continuity summary recorded.'}",
            ]
        )

    @staticmethod
    def _format_support_policy(policy: SupportPolicyDecision) -> str:
        return "\n".join(
            [
                f"- support_mode={policy.support_mode}",
                f"- inferred_preference={policy.inferred_preference}",
                f"- stored_preference={policy.stored_preference}",
                f"- rationale={policy.rationale or 'No additional policy rationale.'}",
            ]
        )

    @classmethod
    def _format_task_experience(cls, task_experience: TaskExperience) -> str:
        lesson_digest = cls._format_memory_entries(
            task_experience.lesson_digest,
            "No lesson digests recorded.",
        )
        domain_tips = "\n".join(
            f"- {domain}: {', '.join(str(item.content) for item in items if str(item.content).strip())}"
            for domain, items in task_experience.domain_tips.items()
            if any(str(item.content).strip() for item in items)
        ) or "- No domain tips recorded."
        agent_habits = "\n".join(
            f"- {agent}: {', '.join(str(item.content) for item in items if str(item.content).strip())}"
            for agent, items in task_experience.agent_habits.items()
            if any(str(item.content).strip() for item in items)
        ) or "- No agent habits recorded."
        return "\n".join(
            [
                "Lesson Digest:",
                lesson_digest,
                "Domain Tips:",
                domain_tips,
                "Agent Habits:",
                agent_habits,
            ]
        )

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

    @classmethod
    def _interpret_emotion(cls, text: str, core_memory: CoreMemory) -> EmotionalInterpretation:
        normalized = text.lower()
        support_preference = cls._resolve_stored_support_preference(core_memory)

        # Use shared constants for detection
        emotion_class = detect_emotion_class(normalized)
        intensity = detect_intensity(normalized, emotion_class)
        duration_hint = detect_duration_hint(normalized)
        emotional_risk = detect_emotional_risk(normalized)

        # Merge carryover from previous session — but guard against
        # "ghost emotion" inheritance on unrelated messages.
        carryover = cls._effective_user_emotional_state(core_memory.user_emotional_state)
        if carryover is not None:
            # Only inherit carryover emotion when the current message is
            # topically related OR the current message itself is emotional.
            # This prevents a neutral "帮我看段代码" from being tagged as
            # anxious just because the previous session had anxiety.
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

            # Support preference is always safe to inherit regardless
            # of topic overlap — it is a user trait, not a momentary signal.
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
    def _build_support_policy(
        cls,
        text: str,
        core_memory: CoreMemory,
        emotional_context: EmotionalInterpretation,
    ) -> SupportPolicyDecision:
        normalized = text.lower()
        carryover = cls._effective_user_emotional_state(core_memory.user_emotional_state)
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

    @staticmethod
    def _resolve_stored_support_preference(core_memory: CoreMemory) -> str:
        carryover = SoulEngine._effective_user_emotional_state(core_memory.user_emotional_state)
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
    def _effective_user_emotional_state(
        state: UserEmotionalState,
    ) -> UserEmotionalState | None:
        if not state.carryover_until and not state.last_observed_at:
            return None
        now = datetime.now(timezone.utc)
        carryover_until = SoulEngine._parse_timestamp(state.carryover_until)
        if carryover_until is not None and carryover_until < now:
            return None
        if carryover_until is None:
            last_observed_at = SoulEngine._parse_timestamp(state.last_observed_at)
            if last_observed_at is None or now - last_observed_at > timedelta(days=7):
                return None
        return state

    @staticmethod
    def _effective_agent_continuity_state(
        state: AgentContinuityState,
    ) -> AgentContinuityState | None:
        """Return the agent continuity state with gradual decay.

        Instead of a hard 7-day cliff, the state gracefully decays:
        - Days 0-3: full state as-is
        - Days 3-7: caution_level is reduced, repair_mode cleared
        - Day 7+: returns None
        """
        if (
            not state.last_event_at
            and not state.active_signals
            and not state.last_shift_reason
            and not state.continuity_summary
        ):
            return None
        now = datetime.now(timezone.utc)
        reference = SoulEngine._parse_timestamp(state.last_event_at) or SoulEngine._parse_timestamp(state.updated_at)
        if reference is None:
            return None
        elapsed = now - reference
        if elapsed > timedelta(days=7):
            return None
        # Gradual decay: after 3 days, start reducing caution
        if elapsed > timedelta(days=3):
            from copy import copy
            decayed = copy(state)
            if decayed.caution_level == "high":
                decayed.caution_level = "medium"
            elif decayed.caution_level == "medium":
                decayed.caution_level = "low"
            decayed.repair_mode = False
            # Reduce relational_confidence decay (partially recovered)
            decayed.relational_confidence = min(
                0.7, decayed.relational_confidence + 0.1
            )
            return decayed
        return state

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
    def _emotional_risk(text: str) -> str:
        return detect_emotional_risk(text)

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
