"""OpenCode-backed code execution agent."""

from __future__ import annotations

import json
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from app.agents.base import SubAgent
from app.config import settings
from app.platform.base import HitlRequest
from app.tasks.models import Task, TaskResult


TASK_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "执行结果摘要"},
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
            "description": "改动的文件路径列表",
        },
        "success": {"type": "boolean"},
        "error_type": {"type": "string", "enum": ["RETRYABLE", "FATAL", "NONE"]},
        "error_msg": {"type": "string"},
    },
    "required": ["summary", "success", "error_type", "error_msg"],
}


class CodeAgent(SubAgent):
    """Translate internal task requests into OpenCode session calls."""

    name = "code_agent"
    domain = "code"

    HIGH_RISK_PERMISSIONS = {"network_request", "dangerous_shell", "delete_files"}

    def __init__(
        self,
        task_store: Any,
        blackboard: Any,
        task_system: Any,
        *,
        base_url: str | None = None,
    ) -> None:
        self.task_store = task_store
        self.blackboard = blackboard
        self.task_system = task_system
        self.base_url = (base_url or settings.opencode.base_url).rstrip("/")

    async def estimate_capability(self, task: Task) -> float:
        text = f"{task.intent}\n{task.prompt_snapshot}".lower()
        score = 0.0
        high = ["代码", "编程", "实现", "脚本", "debug", "调试", "重构", "python", "函数", "类", "run"]
        medium = ["文件", "测试", "命令", "终端", "repo", "git"]
        negative = ["搜索网页", "联网", "浏览器", "图像生成"]
        for keyword in high:
            if keyword in text:
                score += 0.18
        for keyword in medium:
            if keyword in text:
                score += 0.08
        for keyword in negative:
            if keyword in text:
                score -= 0.18
        return max(0.0, min(1.0, score if score > 0 else 0.05))

    async def execute(self, task: Task) -> TaskResult:
        timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            session_id = await self._create_session(client, task)
            task.metadata["opencode_session_id"] = session_id
            await self.task_store.update(task)
            try:
                prompt = self._build_prompt(task)
                task.prompt_snapshot = prompt
                await self.task_store.update(task)
                await client.post(
                    f"/session/{session_id}/prompt_async",
                    json={
                        "parts": [{"type": "text", "text": prompt}],
                        "format": {"type": "json_schema", "schema": TASK_RESULT_SCHEMA},
                    },
                )
                return await self._listen_until_done(client, session_id, task)
            finally:
                if task.status != "waiting_hitl":
                    await self._safe_delete_session(client, session_id)
                    task.metadata.pop("opencode_session_id", None)
                    await self.task_store.update(task)

    async def resume(self, task: Task, hitl_result: dict[str, Any]) -> TaskResult:
        await self.task_system.register_hitl_response(
            task.id,
            hitl_result.get("decision", "reject"),
            hitl_result.get("payload", {}),
        )
        return TaskResult(task_id=task.id, status="running", output={"summary": "permission response received"})

    async def _create_session(self, client: httpx.AsyncClient, task: Task) -> str:
        response = await client.post("/session", json={"title": f"task:{task.id}"})
        response.raise_for_status()
        return str(response.json()["id"])

    async def _listen_until_done(self, client: httpx.AsyncClient, session_id: str, task: Task) -> TaskResult:
        async with aconnect_sse(client, "GET", "/global/event") as event_source:
            async for sse in event_source.aiter_sse():
                await self.emit_heartbeat(task)
                if not sse.data:
                    continue
                try:
                    data = json.loads(sse.data)
                except json.JSONDecodeError:
                    continue
                if data.get("sessionID") != session_id:
                    continue

                event_type = data.get("type", "")
                if event_type == "permission":
                    decision = await self._handle_permission(client, session_id, task, data)
                    if decision == "reject":
                        await self._safe_delete_session(client, session_id)
                        task.metadata.pop("opencode_session_id", None)
                        await self.blackboard.on_task_failed(task, "HITL_REJECTED: user denied permission")
                        return TaskResult(
                            task_id=task.id,
                            status="interrupted",
                            error="HITL rejected",
                            metadata={"error_type": "FATAL"},
                        )
                elif event_type in {"complete", "session.complete"}:
                    return await self._fetch_result(client, session_id, task)
                elif event_type == "error":
                    error_msg = data.get("message", "OpenCode internal error")
                    return TaskResult(
                        task_id=task.id,
                        status="failed",
                        error=error_msg,
                        metadata={"error_type": "RETRYABLE"},
                    )

        return TaskResult(
            task_id=task.id,
            status="failed",
            error="OpenCode event stream closed before completion",
            metadata={"error_type": "RETRYABLE"},
        )

    async def _handle_permission(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        task: Task,
        event: dict[str, Any],
    ) -> str:
        permission_id = str(event["permissionID"])
        permission_type = str(event.get("permissionType", "")).lower()

        if permission_type not in self.HIGH_RISK_PERMISSIONS:
            await client.post(
                f"/session/{session_id}/permissions/{permission_id}",
                json={"response": "approve", "remember": False},
            )
            return "approve"

        request = HitlRequest(
            task_id=task.id,
            title="需要权限确认",
            description=f"任务请求高风险权限：{permission_type}",
            risk_level="high",
            metadata={
                "permission_id": permission_id,
                "permission_type": permission_type,
                "session_id": session_id,
            },
        )
        await self.blackboard.on_task_waiting_hitl(task, request)
        response = await self.task_system.wait_for_hitl_response(task.id)
        decision = response.get("decision", "reject")
        await client.post(
            f"/session/{session_id}/permissions/{permission_id}",
            json={"response": "approve" if decision == "approve" else "reject", "remember": False},
        )
        task.status = "running"
        await self.task_store.update(task)
        return decision

    async def _fetch_result(self, client: httpx.AsyncClient, session_id: str, task: Task) -> TaskResult:
        response = await client.get(f"/session/{session_id}/message")
        response.raise_for_status()
        messages = response.json()

        structured = None
        for message in reversed(messages):
            info = message.get("info", {})
            if info.get("role") == "assistant":
                structured = info.get("structured_output")
                if structured:
                    break

        if structured and structured.get("success"):
            return TaskResult(
                task_id=task.id,
                status="done",
                output={
                    "summary": structured["summary"],
                    "files_changed": structured.get("files_changed", []),
                },
                metadata={"error_type": "NONE"},
            )

        error_type = structured.get("error_type", "RETRYABLE") if structured else "RETRYABLE"
        error_msg = structured.get("error_msg", "no structured output") if structured else "no structured output"
        return TaskResult(
            task_id=task.id,
            status="failed",
            error=f"{error_type}: {error_msg}",
            metadata={"error_type": error_type},
        )

    async def _safe_delete_session(self, client: httpx.AsyncClient, session_id: str) -> None:
        try:
            await client.delete(f"/session/{session_id}")
        except Exception:
            return

    def _build_prompt(self, task: Task) -> str:
        return f"""任务意图：{task.intent}

工作目录：{task.metadata.get("working_dir", ".")}

约束条件：
{task.metadata.get("constraints", "无特殊约束")}

请完成上述任务，并严格按 JSON Schema 返回结果。"""
