import json
from typing import TYPE_CHECKING, Optional

from domain.evolution import Lesson
from domain.task import Task

if TYPE_CHECKING:
    from services.llm import LLMInterface


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


class MetaCognitionReflector:
    """
    元认知反思器：从任务完成/失败中归因生成 Lesson。
    订阅 task_completed (P1) 和 task_failed (P0，立即触发)。
    """

    def __init__(self, llm_lite: "LLMInterface"):
        self._llm = llm_lite

    async def reflect(self, task: Task) -> Optional[Lesson]:
        prompt = REFLECTION_PROMPT_TEMPLATE.format(
            task_id=task.id,
            task_snapshot=task.prompt_snapshot or "无",
            task_result=task.result or "无",
            error_trace=task.error_trace or "无",
            domain=task.metadata.get("domain", "unknown"),
            outcome=task.status,
        )

        response = await self._llm.generate(prompt)
        if not response:
            print(
                f"[MetaCognitionReflector] LLM returned empty response for task {task.id}"
            )
            return None

        try:
            result = json.loads(response)
        except json.JSONDecodeError as e:
            print(f"[MetaCognitionReflector] Failed to parse LLM JSON: {e}")
            return None

        confidence = result.get("confidence", 0)
        if confidence < 0.5:
            print(f"[MetaCognitionReflector] Confidence {confidence} < 0.5, skipping")
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
            confidence=confidence,
        )

        print(
            f"[MetaCognitionReflector] Generated lesson: domain={lesson.domain}, "
            f"confidence={confidence:.2f}, is_pattern={lesson.is_pattern}"
        )
        return lesson
