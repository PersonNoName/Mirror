"""Minimal V1 placeholder web agent."""

from __future__ import annotations

from typing import Any

from app.agents.base import SubAgent
from app.tasks.models import Task, TaskResult


class WebAgent(SubAgent):
    """Placeholder agent for non-code information lookups in V1."""

    name = "web_agent"
    domain = "search"

    def __init__(self, task_store: Any) -> None:
        self.task_store = task_store

    async def estimate_capability(self, task: Task) -> float:
        text = f"{task.intent}\n{task.prompt_snapshot}".lower()
        score = 0.0
        keywords = ["搜索", "查找", "资料", "文档", "说明", "网页", "网站", "检索"]
        negatives = ["代码", "脚本", "实现", "重构", "debug", "调试"]
        for keyword in keywords:
            if keyword in text:
                score += 0.16
        for keyword in negatives:
            if keyword in text:
                score -= 0.12
        return max(0.0, min(0.55, score))

    async def execute(self, task: Task) -> TaskResult:
        summary = (
            "WebAgent 在 V1 仅提供占位闭环，"
            "当前不会执行真实联网抓取或浏览器控制。"
        )
        return TaskResult(
            task_id=task.id,
            status="done",
            output={"summary": summary, "intent": task.intent, "mode": "placeholder"},
            metadata={"error_type": "NONE"},
        )
