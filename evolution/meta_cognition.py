from typing import Optional
from domain.evolution import Lesson
from domain.task import Task


class LLMInterfaceDummy:
    """LLM 调用占位实现"""

    async def generate(self, prompt: str) -> dict:
        print(f"[LLM] 反思生成调用（占位）")
        return {
            "confidence": 0.6,
            "root_cause": "mock_root_cause",
            "lesson": "mock_lesson",
            "domain": "general",
            "is_agent_capability_issue": False,
        }


class MetaCognitionReflector:
    """
    元认知反思器：从任务完成/失败中归因生成 Lesson。
    订阅 task_completed (P1) 和 task_failed (P0，立即触发)。
    """

    REFLECTION_PROMPT_TEMPLATE = """
任务执行结果：
- 任务ID: {task_id}
- 任务状态: {outcome}
- Prompt快照: {task_snapshot}
- 执行结果: {task_result}
- 错误trace: {error_trace}
- 领域: {domain}

请进行归因分析，输出JSON：
{{
    "confidence": 0.0-1.0的置信度,
    "root_cause": "根本原因分析",
    "lesson": "经验教训总结",
    "domain": "任务领域",
    "is_agent_capability_issue": true/false,
    "is_pattern": true/false,
    "subject": "如为pattern，主体",
    "relation": "如为pattern，关系",
    "object": "如为pattern，客体"
}}

置信度低于0.5的反思将被丢弃。
"""

    def __init__(
        self,
        llm_lite: Optional[LLMInterfaceDummy] = None,
    ):
        self.llm_lite = llm_lite or LLMInterfaceDummy()

    async def reflect(self, task: Task) -> Optional[Lesson]:
        """
        对任务执行结果进行反思，生成 Lesson。
        """
        prompt = self.REFLECTION_PROMPT_TEMPLATE.format(
            task_id=task.id,
            task_snapshot=task.prompt_snapshot or "无",
            task_result=task.result or "无",
            error_trace=task.error_trace or "无",
            domain=task.metadata.get("domain", "unknown"),
            outcome=task.status,
        )

        result = await self.llm_lite.generate(prompt)

        if result.get("confidence", 0) < 0.5:
            print(f"[MetaCognitionReflector] 置信度 {result['confidence']} < 0.5，跳过")
            return None

        lesson = Lesson(
            task_id=task.id,
            domain=result.get("domain", task.metadata.get("domain", "unknown")),
            outcome=task.status,
            root_cause=result.get("root_cause", ""),
            lesson_text=result.get("lesson", ""),
            is_agent_capability_issue=result.get("is_agent_capability_issue", False),
            is_pattern=result.get("is_pattern", False),
            subject=result.get("subject"),
            relation=result.get("relation"),
            object=result.get("object"),
            confidence=result.get("confidence", 0.5),
        )

        return lesson
