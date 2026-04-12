"""Prompt section formatting extracted from SoulEngine."""

from __future__ import annotations

from typing import Any

from app.memory import (
    AgentContinuityState,
    AgentEmotionalState,
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
from app.prompts import render_soul_core_system_prompt
from app.soul.emotion_interpreter import EmotionInterpreter
from app.soul.models import EmotionalInterpretation, SupportPolicyDecision


class PromptAssembler:
    """Stateless helper that assembles prompt sections and brain snapshots."""

    def __init__(self, proactivity_service: Any | None = None) -> None:
        self.proactivity_service = proactivity_service

    def build_prompt(
        self,
        core_memory: CoreMemory,
        recent_messages: list[dict[str, Any]],
        session_adaptations_live: list[str],
        mid_term_memories: list[MidTermMemoryItem],
        retrieved: dict[str, Any],
        emotional_context: EmotionalInterpretation,
        support_policy: SupportPolicyDecision,
        tool_registry: Any,
    ) -> str:
        tool_list = self._build_tool_list(tool_registry)
        behavioral_rules = self._build_behavioral_rules(core_memory)
        session_adaptations = self._build_session_adaptations(core_memory, session_adaptations_live)
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
                    shared_experiences=self._format_shared_experiences(core_memory.world_model),
                    agent_emotional_state=self._format_agent_emotional_state(
                        core_memory.agent_emotional_state
                    ),
                    proactivity_policy=self._format_proactivity_policy(core_memory),
                    emotional_context=self._format_emotional_context(emotional_context),
                    user_emotional_state=self._format_user_emotional_state(
                        EmotionInterpreter.effective_user_emotional_state(core_memory.user_emotional_state)
                    ),
                    agent_continuity_state=self._format_agent_continuity_state(
                        EmotionInterpreter.effective_agent_continuity_state(core_memory.agent_continuity_state)
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

    def build_brain_snapshot(
        self,
        core_memory: CoreMemory,
        recent_messages: list[dict[str, Any]],
        session_adaptations_live: list[str],
        mid_term_memories: list[MidTermMemoryItem],
        retrieved: dict[str, Any],
        emotional_context: EmotionalInterpretation,
        support_policy: SupportPolicyDecision,
        tool_registry: Any,
    ) -> dict[str, str]:
        tool_list = self._build_tool_list(tool_registry)
        behavioral_rules = self._build_behavioral_rules(core_memory)
        session_adaptations = self._build_session_adaptations(core_memory, session_adaptations_live)

        return {
            "self_cognition": self._format_self_cognition(core_memory),
            "world_model": self._format_world_model(core_memory.world_model),
            "stable_identity": self._format_stable_identity(core_memory, behavioral_rules),
            "relationship_style": self._format_relationship_style(core_memory),
            "relationship_stage": self._format_relationship_stage(core_memory.world_model),
            "shared_experiences": self._format_shared_experiences(core_memory.world_model),
            "agent_emotional_state": self._format_agent_emotional_state(
                core_memory.agent_emotional_state
            ),
            "proactivity_policy": self._format_proactivity_policy(core_memory),
            "emotional_context": self._format_emotional_context(emotional_context),
            "user_emotional_state": self._format_user_emotional_state(
                EmotionInterpreter.effective_user_emotional_state(core_memory.user_emotional_state)
            ),
            "agent_continuity_state": self._format_agent_continuity_state(
                EmotionInterpreter.effective_agent_continuity_state(core_memory.agent_continuity_state)
            ),
            "support_policy": self._format_support_policy(support_policy),
            "session_adaptations": (
                "These adaptations are temporary and only apply to the current session.\n"
                f"{session_adaptations}"
            ),
            "task_experience": self._format_task_experience(core_memory.task_experience),
            "tool_list": tool_list,
        }

    # ------------------------------------------------------------------
    # Private helpers — shared build logic
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tool_list(tool_registry: Any) -> str:
        tool_descriptions = tool_registry.describe_tools()
        return "\n".join(
            f"- {item['name']}: {item['description'] or 'No description'} | schema={item['schema']}"
            for item in tool_descriptions
        ) or "- No tools are currently registered."

    @staticmethod
    def _build_behavioral_rules(core_memory: CoreMemory) -> str:
        core_personality = core_memory.personality.core_personality
        return "\n".join(
            f"- {rule.rule}" for rule in core_personality.behavioral_rules
        ) or "- No persistent behavioral rules."

    @staticmethod
    def _build_session_adaptations(core_memory: CoreMemory, session_adaptations_live: list[str]) -> str:
        persisted_adaptations = list(core_memory.personality.session_adaptation.current_items)
        merged_adaptations = persisted_adaptations + [
            item for item in session_adaptations_live if item not in persisted_adaptations
        ]
        return "\n".join(
            f"- {item}" for item in merged_adaptations
        ) or "- No active session adaptations for this session."

    # ------------------------------------------------------------------
    # Section formatters
    # ------------------------------------------------------------------

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
            world_model.confirmed_facts, "No confirmed facts recorded.",
        )
        inferred_memories = cls._format_durable_entries(
            world_model.inferred_memories, "No inferred memories recorded.",
        )
        relationship_history = cls._format_relationship_entries(
            world_model.relationship_history, "No relationship history recorded.",
        )
        pending_confirmations = cls._format_durable_entries(
            world_model.pending_confirmations, "No pending confirmations.",
        )
        memory_conflicts = cls._format_durable_entries(
            world_model.memory_conflicts, "No memory conflicts recorded.",
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

    @staticmethod
    def _format_agent_emotional_state(state: AgentEmotionalState) -> str:
        curiosity = ", ".join(state.curiosity_topics[:5]) if state.curiosity_topics else "none"
        affinities = "\n".join(
            f"  - {a.topic}: engagement={a.engagement_level:.2f}, sentiment={a.sentiment}"
            for a in state.topic_affinities[:5]
        ) or "  - No topic affinities recorded."
        return "\n".join(
            [
                f"- mood={state.mood}",
                f"- mood_intensity={state.mood_intensity}",
                f"- mood_reason={state.mood_reason or 'No specific reason.'}",
                f"- toward_user={state.toward_user}",
                f"- toward_user_intensity={state.toward_user_intensity}",
                f"- toward_user_reason={state.toward_user_reason or 'No specific reason.'}",
                f"- emotional_valence={state.emotional_valence:.2f}",
                f"- curiosity_topics={curiosity}",
                f"- last_interaction_at={state.last_interaction_at or 'unknown'}",
                "Topic Affinities:",
                affinities,
            ]
        )

    @staticmethod
    def _format_shared_experiences(world_model: WorldModel) -> str:
        experiences = world_model.shared_experiences
        if not experiences:
            return "- No shared experiences recorded yet."
        lines = []
        for exp in experiences[:5]:
            lines.append(
                f"- [{exp.emotional_tone}|{exp.importance}|{exp.created_at[:10]}] {exp.summary}"
            )
        return "\n".join(lines)

    @classmethod
    def _format_task_experience(cls, task_experience: TaskExperience) -> str:
        lesson_digest = cls._format_memory_entries(
            task_experience.lesson_digest, "No lesson digests recorded.",
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
