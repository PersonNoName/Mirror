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
from app.soul.models import Action


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
        prompt = self._build_prompt(core_memory, recent_messages, session_adaptations, retrieved)

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
    def _format_durable_entries(entries: list[DurableMemory], empty_text: str) -> str:
        lines = []
        for entry in entries:
            content = str(entry.content).strip()
            if not content:
                continue
            status = "confirmed" if entry.confirmed_by_user else entry.status
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
