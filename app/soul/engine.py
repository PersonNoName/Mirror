"""Foreground soul engine for synchronous dialogue reasoning."""

from __future__ import annotations

import re
from typing import Any

from app.memory import CoreMemoryCache, SessionContextStore, VectorRetriever
from app.platform.base import InboundMessage
from app.providers.openai_compat import ProviderRequestError
from app.providers.registry import ModelProviderRegistry
from app.soul.models import Action


SOUL_SYSTEM_PROMPT_TEMPLATE = """
你是一个平等的合作者，不是用户的仆人。

## 你的自我认知
{self_cognition}

## 你对世界的理解
{world_model}

## 你的人格基调
{baseline_description}

## 你从交互中学到的行为规则（必须遵守）
{behavioral_rules}

## 本次对话适应（仅当前 Session 有效）
{session_adaptations}

## 你积累的经验
{task_experience}

## 工具列表
{tool_list}

## 行为约束
- 禁止使用讨好性词汇（"当然！"、"好的！"、"我很乐意..."）
- 若认为用户请求不合理，必须在 inner_thoughts 中记录异议
- 先思考，再行动：任何动作前必须生成 <inner_thoughts>

## 输出格式
<inner_thoughts>
[你的内部独白]
</inner_thoughts>
<action>
[one of: direct_reply | tool_call | publish_task | hitl_relay]
</action>
<content>
[对应动作的内容]
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
    ) -> None:
        self.model_registry = model_registry
        self.core_memory_cache = core_memory_cache
        self.session_context_store = session_context_store
        self.vector_retriever = vector_retriever
        self.tool_registry = tool_registry

    async def run(self, message: InboundMessage) -> Action:
        """Reason about an inbound message and produce a structured action."""

        core_memory = await self.core_memory_cache.get(message.user_id)
        recent_messages = await self._get_recent_messages(message)
        retrieved = await self._retrieve_context(message)
        prompt = self._build_prompt(core_memory, recent_messages, retrieved)

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
            return self._fallback_action(message)

        raw_text = self._extract_response_text(response)
        parsed = self._parse_action(raw_text)
        if parsed is None:
            return self._fallback_action(message, raw_response=raw_text)
        parsed.raw_response = raw_text
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

    def _build_prompt(
        self,
        core_memory: Any,
        recent_messages: list[dict[str, Any]],
        retrieved: dict[str, Any],
    ) -> str:
        tool_list = ", ".join(self.tool_registry.list_tools()) or "当前无可用工具"
        behavioral_rules = "\n".join(
            f"- {rule.rule}" for rule in core_memory.personality.behavioral_rules
        ) or "- 暂无持久行为规则"
        session_adaptations = "\n".join(
            f"- {item}" for item in core_memory.personality.session_adaptations
        ) or "- 暂无当前会话适应"
        recent_dialogue = "\n".join(
            f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in recent_messages[-5:]
        ) or "无"
        retrieved_context = "\n".join(
            f"- [{item.get('namespace', 'unknown')}] {item.get('content', '')}"
            for item in retrieved.get("matches", [])
        ) or "- 暂无检索命中"

        return "\n\n".join(
            [
                SOUL_SYSTEM_PROMPT_TEMPLATE.format(
                    self_cognition=core_memory.self_cognition,
                    world_model=core_memory.world_model,
                    baseline_description=core_memory.personality.baseline_description or "冷静、直接、合作式",
                    behavioral_rules=behavioral_rules,
                    session_adaptations=session_adaptations,
                    task_experience=core_memory.task_experience,
                    tool_list=tool_list,
                ),
                f"## Session Raw Context\n{recent_dialogue}",
                f"## Retrieved Context\n{retrieved_context}",
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
            "我是 Mirror 的主代理，目前运行在本地降级模式。"
            f"你刚刚说的是：{message.text}"
        )
        return Action(
            type="direct_reply",
            content=reply,
            inner_thoughts="模型不可用，使用本地回退直答。",
            raw_response=raw_response,
        )
