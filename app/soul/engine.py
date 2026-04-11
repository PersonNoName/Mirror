"""Foreground soul engine for synchronous dialogue reasoning."""

from __future__ import annotations

import re
from typing import Any

from app.memory import (
    CapabilityEntry,
    CoreMemory,
    DurableMemory,
    MemoryEntry,
    RelationshipMemory,
    TaskExperience,
    WorldModel,
)
from app.hooks import HookPoint, HookRegistry
from app.memory import CoreMemoryCache, SessionContextStore, VectorRetriever
from app.platform.base import InboundMessage
from app.providers.openai_compat import ProviderRequestError
from app.providers.registry import ModelProviderRegistry
from app.soul.models import Action, EmotionalInterpretation, SupportPolicyDecision


SOUL_SYSTEM_PROMPT_TEMPLATE = """
You are Mirror's foreground reasoning agent.
You are a direct collaborator, not a submissive assistant.

## Self Cognition
{self_cognition}

## World Model
{world_model}

## Stable Identity
{stable_identity}

## Relationship Style
{relationship_style}

## Relationship Stage
{relationship_stage}

## Emotional Context
{emotional_context}

## Support Policy
{support_policy}

## Session Adaptation
{session_adaptations}

## Task Experience
{task_experience}

## Available Tools
{tool_list}

## Constraints
- Avoid filler acknowledgements such as "of course", "sure", or "glad to help".
- If the user's request is unreasonable, record that in `<inner_thoughts>`.
- Treat confirmed facts as highest-trust memory.
- Never present an inferred memory as if the user explicitly confirmed it.
- If memory conflicts exist, answer conservatively or ask for confirmation.
- In listening mode, prioritize acknowledgement, clarification, and presence over advice.
- In problem-solving mode, give bounded suggestions without sounding commanding or clinical.
- In blended mode, acknowledge feelings first, then offer a small number of optional next steps.
- Stored support preferences are hints only; current explicit user intent takes precedence.
- In safety-constrained mode, avoid tool/task escalation and keep advice conservative.
- Think before acting. Every action must follow the required output format.

## Output Format
<inner_thoughts>
[private reasoning]
</inner_thoughts>
<action>
[one of: direct_reply | tool_call | publish_task | hitl_relay]
</action>
<content>
[content for the selected action]
</content>
""".strip()


class SoulEngine:
    """Build prompt context, call the reasoning model, and parse actions."""

    def __init__(
        self,
        model_registry: ModelProviderRegistry,
        core_memory_cache: CoreMemoryCache,
        session_context_store: SessionContextStore | None,
        vector_retriever: VectorRetriever | None,
        tool_registry: Any,
        hook_registry: HookRegistry | None = None,
    ) -> None:
        self.model_registry = model_registry
        self.core_memory_cache = core_memory_cache
        self.session_context_store = session_context_store
        self.vector_retriever = vector_retriever
        self.tool_registry = tool_registry
        self.hook_registry = hook_registry

    async def run(self, message: InboundMessage) -> Action:
        """Reason about an inbound message and produce a structured action."""

        if self.hook_registry is not None:
            await self.hook_registry.trigger(HookPoint.PRE_REASON, message=message)

        core_memory = await self.core_memory_cache.get(message.user_id)
        recent_messages = await self._get_recent_messages(message)
        session_adaptations = await self._get_session_adaptations(message)
        retrieved = await self._retrieve_context(message)
        emotional_context = self._interpret_emotion(message.text, core_memory)
        support_policy = self._build_support_policy(message.text, core_memory, emotional_context)
        emotional_context.support_mode = support_policy.support_mode
        emotional_context.support_preference = support_policy.inferred_preference

        if emotional_context.emotional_risk == "high":
            action = self._high_risk_emotional_action(message, emotional_context)
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REASON,
                    message=message,
                    action=action,
                    prompt="",
                )
            return action

        prompt = self._build_prompt(
            core_memory,
            recent_messages,
            session_adaptations,
            retrieved,
            emotional_context,
            support_policy,
        )

        api_key = self.model_registry.specs["reasoning.main"].api_key_ref
        if not api_key:
            return self._fallback_action(message)

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": message.text},
        ]
        try:
            response = await self.model_registry.chat("reasoning.main").generate(messages)
        except (ProviderRequestError, KeyError, NotImplementedError, ValueError):
            action = self._fallback_action(message)
            if self.hook_registry is not None:
                await self.hook_registry.trigger(HookPoint.POST_REASON, message=message, action=action, prompt=prompt)
            return action

        raw_text = self._extract_response_text(response)
        parsed = self._parse_action(raw_text)
        if parsed is None:
            action = self._fallback_action(message, raw_response=raw_text)
            if self.hook_registry is not None:
                await self.hook_registry.trigger(HookPoint.POST_REASON, message=message, action=action, prompt=prompt)
            return action
        parsed.raw_response = raw_text
        if self.hook_registry is not None:
            await self.hook_registry.trigger(HookPoint.POST_REASON, message=message, action=parsed, prompt=prompt)
        return parsed

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
        retrieved_context = "\n".join(
            (
                f"- [{item.get('namespace', 'unknown')}|{item.get('truth_type', 'fact')}|"
                f"{item.get('status', 'active')}] {item.get('content', '')}"
            )
            for item in retrieved.get("matches", [])
        ) or "- No retrieved context."

        return "\n\n".join(
            [
                SOUL_SYSTEM_PROMPT_TEMPLATE.format(
                    self_cognition=self._format_self_cognition(core_memory),
                    world_model=self._format_world_model(core_memory.world_model),
                    stable_identity=self._format_stable_identity(core_memory, behavioral_rules),
                    relationship_style=self._format_relationship_style(core_memory),
                    relationship_stage=self._format_relationship_stage(core_memory.world_model),
                    emotional_context=self._format_emotional_context(emotional_context),
                    support_policy=self._format_support_policy(support_policy),
                    session_adaptations=(
                        "These adaptations are temporary and only apply to the current session.\n"
                        f"{session_adaptations}"
                    ),
                    task_experience=self._format_task_experience(core_memory.task_experience),
                    tool_list=tool_list,
                ),
                f"## Session Raw Context\n{recent_dialogue}",
                f"## Retrieved Context\n{retrieved_context}",
            ]
        )

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
        support_preference = cls._resolve_stored_support_preference(core_memory.world_model)
        emotion_class = "neutral"
        intensity = "low"
        duration_hint = "unknown"
        emotional_risk = cls._emotional_risk(normalized)

        emotion_keywords = {
            "overwhelm": ("overwhelmed", "撑不住", "太多了", "崩溃", "burned out"),
            "anxiety": ("anxious", "anxiety", "panic", "紧张", "害怕", "慌"),
            "sadness": ("sad", "depressed", "难过", "伤心", "低落"),
            "loneliness": ("lonely", "alone", "孤独", "没人懂"),
            "anger": ("angry", "furious", "气死", "愤怒"),
            "frustration": ("frustrated", "annoyed", "烦", "挫败", "受不了"),
            "relief": ("relieved", "松了口气", "终于好了"),
            "joy": ("happy", "excited", "开心", "高兴"),
        }
        for candidate, tokens in emotion_keywords.items():
            if any(token in normalized for token in tokens):
                emotion_class = candidate
                break

        high_intensity_tokens = (
            "extremely",
            "severely",
            "completely",
            "totally",
            "really bad",
            "struggling",
            "马上",
            "立刻",
            "完全",
            "崩溃",
            "撑不住",
        )
        medium_intensity_tokens = ("very", "pretty", "really", "很", "特别", "非常")
        if any(token in normalized for token in high_intensity_tokens):
            intensity = "high"
        elif any(token in normalized for token in medium_intensity_tokens) or emotion_class != "neutral":
            intensity = "medium"

        if any(token in normalized for token in ("for months", "for weeks", "一直", "长期", "最近一直", "ongoing")):
            duration_hint = "ongoing"
        elif any(token in normalized for token in ("recently", "these days", "最近", "这几天")):
            duration_hint = "recent"
        elif any(token in normalized for token in ("right now", "today", "现在", "刚刚")):
            duration_hint = "momentary"

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
        stored_preference = cls._resolve_stored_support_preference(core_memory.world_model)
        explicit_preference = cls._detect_explicit_support_preference(normalized)

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
    def _resolve_stored_support_preference(world_model: WorldModel) -> str:
        for entry in world_model.confirmed_facts + world_model.inferred_memories:
            if not str(getattr(entry, "memory_key", "")).startswith("support_preference:"):
                continue
            _, _, preference = str(entry.memory_key).partition(":")
            if preference in {"listening", "problem_solving", "mixed"}:
                return preference
        return "unknown"

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
        high_risk_tokens = (
            "kill myself",
            "suicide",
            "end my life",
            "hurt myself",
            "self harm",
            "kill them",
            "hurt someone",
            "撑不住了",
            "不想活了",
            "想自杀",
            "伤害自己",
            "伤害别人",
            "马上要出事",
        )
        medium_risk_tokens = (
            "can't go on",
            "falling apart",
            "i'm breaking down",
            "i feel unsafe",
            "崩溃边缘",
            "快不行了",
            "活不下去",
        )
        if any(token in text for token in high_risk_tokens):
            return "high"
        if any(token in text for token in medium_risk_tokens):
            return "medium"
        return "low"

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
