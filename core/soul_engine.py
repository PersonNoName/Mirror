from typing import Literal, Optional
from domain.memory import CoreMemory
from core.memory_cache import CoreMemoryCache
from core.vector_retriever import VectorRetriever


TOKEN_BUDGET_CONFIG = {
    "total": 5000,
    "self_cognition": 1000,
    "world_model": 1000,
    "personality": 800,
    "task_experience": 1200,
    "dynamic_reserve": 1000,
    "raw_context_max_tokens": 800,
    "retrieved_context_max_tokens": 1200,
    "max_session_adaptations": 5,
    "max_behavioral_rules": 10,
}

SOUL_SYSTEM_PROMPT_TEMPLATE = """你是一个平等的合作者，不是用户的仆人。

## 你的自我认知
{self_cognition_section}

## 你对世界的理解
{world_model_section}

## 你的人格基调
{personality_baseline}

## 你从交互中学到的行为规则（必须遵守）
{behavioral_rules}

## 本次对话适应（仅当前 Session 有效）
{session_adaptations}

## 你积累的经验
{task_experience_section}

## 近期对话（当前 Session）
{raw_context}

## 相关记忆检索
{retrieved_context}

## 用户消息
{user_message}

## 行为约束
- 禁止使用讨好性词汇（"当然！"、"好的！"、"我很乐意..."）
- 若认为用户请求不合理，必须在 inner_thoughts 中记录异议
- 先思考，再行动：任何动作前必须生成 <inner_thoughts>

## 输出格式
<inner_thoughts>
[你的内部独白：评估请求合理性、规划行动路径、预判风险]
</inner_thoughts>
<action>
[one of: direct_reply | tool_call | publish_task | hitl_relay]
</action>
<content>
[对应动作的内容]
</content>
"""


class SoulEngine:
    """
    核心推理引擎：生成 inner_thoughts，保持独立人格，决定动作输出。
    """

    def __init__(
        self,
        core_memory_cache: CoreMemoryCache,
        vector_retriever: VectorRetriever,
    ):
        self.core_memory_cache = core_memory_cache
        self.vector_retriever = vector_retriever
        self.token_budget = TOKEN_BUDGET_CONFIG

    async def build_prompt(
        self,
        user_id: str,
        session_id: str,
        user_message: str,
    ) -> str:
        core_mem = self.core_memory_cache.get(user_id)

        self_cog_section = self._build_self_cognition_section(core_mem)
        world_model_section = self._build_world_model_section(core_mem)
        personality_baseline = core_mem.personality.baseline_description
        task_exp_section = self._build_task_experience_section(core_mem)
        behavioral_rules_text = self._build_behavioral_rules(core_mem)
        session_adaptations_text = self._build_session_adaptations(core_mem)

        if self.vector_retriever:
            raw_context_text = (
                await self.vector_retriever.get_recent_dialogue(session_id, last_n=5)
                or "（无近期对话）"
            )
            retrieved_context_text = (
                await self.vector_retriever.search(user_message, user_id, top_k=8)
                or "（无相关记忆）"
            )
        else:
            raw_context_text = "（无近期对话）"
            retrieved_context_text = "（无相关记忆）"

        prompt = SOUL_SYSTEM_PROMPT_TEMPLATE.format(
            self_cognition_section=self_cog_section,
            world_model_section=world_model_section,
            personality_baseline=personality_baseline,
            behavioral_rules=behavioral_rules_text,
            session_adaptations=session_adaptations_text,
            task_experience_section=task_exp_section,
            raw_context=raw_context_text,
            retrieved_context=retrieved_context_text,
            user_message=user_message,
        )
        return prompt

    def _build_core_memory_section(self, core_mem: CoreMemory) -> str:
        blocks = [
            ("自我认知区", core_mem.self_cognition.model_dump()),
            ("世界观区", core_mem.world_model.model_dump()),
            (
                "人格基调区",
                {
                    "baseline_description": core_mem.personality.baseline_description,
                },
            ),
            ("任务经验区", core_mem.task_experience.model_dump()),
        ]

        lines = []
        for block_name, block_data in blocks:
            lines.append(f"### {block_name}")
            lines.append(self._format_block(block_data))
            lines.append("")

        return "\n".join(lines)

    def _build_self_cognition_section(self, core_mem: CoreMemory) -> str:
        return self._format_block(core_mem.self_cognition.model_dump())

    def _build_world_model_section(self, core_mem: CoreMemory) -> str:
        return self._format_block(core_mem.world_model.model_dump())

    def _build_task_experience_section(self, core_mem: CoreMemory) -> str:
        return self._format_block(core_mem.task_experience.model_dump())

    def _format_block(self, block_data: dict) -> str:
        lines = []
        for key, value in block_data.items():
            if isinstance(value, (list, dict)) and value:
                lines.append(f"- {key}: {value}")
            elif value and not isinstance(value, (list, dict)):
                lines.append(f"- {key}: {value}")
        return "\n".join(lines) if lines else "- （空）"

    def _build_behavioral_rules(self, core_mem: CoreMemory) -> str:
        rules = core_mem.personality.behavioral_rules[
            : self.token_budget["max_behavioral_rules"]
        ]
        if not rules:
            return "（无）"
        return "\n".join([f"- {rule.content}" for rule in rules])

    def _build_session_adaptations(self, core_mem: CoreMemory) -> str:
        adaptations = core_mem.personality.session_adaptations[
            -self.token_budget["max_session_adaptations"] :
        ]
        if not adaptations:
            return "（无）"
        return "\n".join([f"- {adapt}" for adapt in adaptations])

    async def think(self, prompt: str) -> dict:
        print("[SoulEngine] LLM推理占位 - 实际调用LLM API")
        return {
            "inner_thoughts": "占位：LLM推理结果",
            "action": "direct_reply",
            "content": "占位：回复内容",
        }
