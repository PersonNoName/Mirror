import asyncio
import json
from typing import Optional, Any, TYPE_CHECKING
import httpx
from httpx_sse import aconnect_sse

from domain.task import Task, TaskResult
from interfaces.agents import SubAgent

if TYPE_CHECKING:
    from interfaces.storage import TaskStoreInterface
    from core.memory_cache import CoreMemoryCache


OPENCODE_BASE_URL = "http://127.0.0.1:4096"

TASK_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "success": {"type": "boolean"},
        "error_type": {"type": "string", "enum": ["RETRYABLE", "FATAL", "NONE"]},
        "error_msg": {"type": "string"},
    },
    "required": ["summary", "success", "error_type"],
}

HIGH_RISK_PERMISSIONS = {"network_request", "dangerous_shell", "delete_files"}


class CodeAgent(SubAgent):
    """
    CodeAgent：OpenCode HTTP 协议适配器。
    本身不含任何代码执行智能，负责将 Task 协议翻译为 OpenCode HTTP 调用，
    并将结果翻译回 TaskResult。
    """

    name = "code_agent"
    domain = "code"

    def __init__(
        self,
        task_store: "TaskStoreInterface",
        blackboard: Any,
        core_memory_cache: Optional["CoreMemoryCache"] = None,
    ):
        self.task_store = task_store
        self.blackboard = blackboard
        self.core_memory_cache = core_memory_cache

    async def execute(self, task: Task) -> TaskResult:
        async with httpx.AsyncClient(timeout=None) as client:
            session_id = None
            try:
                session_id = await self._create_session(client, task)
                prompt = self._build_prompt(task)
                task.prompt_snapshot = prompt
                await self.task_store.update(task)

                await self._send_prompt_async(client, session_id, prompt)
                result = await self._listen_until_done(client, session_id, task)
                return result

            except httpx.HTTPError as e:
                error_msg = f"HTTP Error: {e}"
                print(f"[CodeAgent] {error_msg}")
                await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
                return TaskResult(
                    task_id=task.id,
                    status="failed",
                    error_trace=f"RETRYABLE: {error_msg}",
                )
            except Exception as e:
                error_msg = f"Unexpected error: {e}"
                print(f"[CodeAgent] {error_msg}")
                await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
                return TaskResult(
                    task_id=task.id,
                    status="failed",
                    error_trace=f"RETRYABLE: {error_msg}",
                )
            finally:
                if session_id:
                    await self._cleanup_session(client, session_id)

    async def estimate_capability(self, task: Task) -> float:
        """
        两级评分：关键词快速匹配 + Core Memory 历史成功率加权。
        必须轻量，无网络调用，<10ms。
        """
        CODE_KEYWORDS = {
            "high": [
                "代码",
                "编程",
                "实现",
                "脚本",
                "debug",
                "调试",
                "重构",
                "函数",
                "类",
                "算法",
            ],
            "low": ["文件", "运行", "执行", "测试"],
            "exclusive": ["搜索", "网页", "天气", "新闻", "翻译"],
        }

        text = task.intent.lower()
        keyword_score = 0.0

        for kw in CODE_KEYWORDS["high"]:
            if kw in text:
                keyword_score = min(1.0, keyword_score + 0.2)

        for kw in CODE_KEYWORDS["low"]:
            if kw in text:
                keyword_score = min(1.0, keyword_score + 0.1)

        for kw in CODE_KEYWORDS["exclusive"]:
            if kw in text:
                keyword_score = max(0.0, keyword_score - 0.3)

        history_confidence = 0.5
        if self.core_memory_cache:
            history_confidence = await self._get_capability_confidence("code")

        return keyword_score * 0.6 + history_confidence * 0.4

    async def cancel(self) -> None:
        print(f"[CodeAgent] cancel called for {self.name}")

    async def emit_heartbeat(self, task: Task) -> None:
        task.last_heartbeat_at = task.last_heartbeat_at
        await self.task_store.update_heartbeat(task.id, task.last_heartbeat_at)

    async def resume(self, task: Task, hitl_result: dict) -> TaskResult:
        print(f"[CodeAgent] resume called for task {task.id}")
        return await self.execute(task)

    async def _create_session(self, client: httpx.AsyncClient, task: Task) -> str:
        resp = await client.post(
            f"{OPENCODE_BASE_URL}/session",
            json={"title": f"task:{task.id}"},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def _send_prompt_async(
        self, client: httpx.AsyncClient, session_id: str, prompt: str
    ) -> None:
        await client.post(
            f"{OPENCODE_BASE_URL}/session/{session_id}/prompt_async",
            json={
                "parts": [{"type": "text", "text": prompt}],
                "format": {"type": "json_schema", "schema": TASK_RESULT_SCHEMA},
            },
        )

    async def _listen_until_done(
        self, client: httpx.AsyncClient, session_id: str, task: Task
    ) -> TaskResult:
        """
        监听 SSE 全局事件流，直到当前 session 完成。
        每条事件都刷新心跳。
        """
        async with aconnect_sse(
            client, "GET", f"{OPENCODE_BASE_URL}/global/event"
        ) as event_source:
            async for sse in event_source.aiter_sse():
                await self.emit_heartbeat(task)

                data = json.loads(sse.data)
                if data.get("sessionID") != session_id:
                    continue

                event_type = data.get("type")

                if event_type == "permission":
                    await self._handle_permission(client, session_id, task, data)

                elif event_type in ("complete", "session.complete"):
                    return await self._fetch_result(client, session_id, task)

                elif event_type == "error":
                    error_msg = data.get("message", "OpenCode internal error")
                    await self.blackboard.on_task_failed(
                        task, f"RETRYABLE: {error_msg}"
                    )
                    return TaskResult(
                        task_id=task.id,
                        status="failed",
                        error_trace=f"RETRYABLE: {error_msg}",
                    )

    async def _handle_permission(
        self,
        client: httpx.AsyncClient,
        session_id: str,
        task: Task,
        event: dict,
    ) -> None:
        """
        权限请求分级处理：
        - 低风险 → 自动 approve
        - 高风险 → 升级 HITL，挂起等待用户确认
        """
        permission_id = event.get("permissionID")
        permission_type = event.get("permissionType", "")

        if permission_type in HIGH_RISK_PERMISSIONS:
            await self.blackboard.on_task_failed(
                task, f"HITL_REQUIRED: permission={permission_type}"
            )
            return

        await client.post(
            f"{OPENCODE_BASE_URL}/session/{session_id}/permissions/{permission_id}",
            json={"response": "approve", "remember": False},
        )

    async def _fetch_result(
        self, client: httpx.AsyncClient, session_id: str, task: Task
    ) -> TaskResult:
        """
        取最终消息，解析 structured_output，转换为 TaskResult。
        """
        resp = await client.get(f"{OPENCODE_BASE_URL}/session/{session_id}/message")
        messages = resp.json()

        structured = None
        for msg in reversed(messages):
            if msg.get("info", {}).get("role") == "assistant":
                structured = msg.get("info", {}).get("structured_output")
                break

        if structured and structured.get("success"):
            await self.blackboard.on_task_complete(task)
            return TaskResult(
                task_id=task.id,
                status="done",
                result={
                    "summary": structured.get("summary"),
                    "files_changed": structured.get("files_changed", []),
                },
                summary=structured.get("summary"),
                files_changed=structured.get("files_changed", []),
            )

        error_type = "RETRYABLE"
        error_msg = "unknown"

        if structured:
            error_type = structured.get("error_type", "RETRYABLE")
            error_msg = structured.get("error_msg", "unknown")

        full_error = f"{error_type}: {error_msg}"
        await self.blackboard.on_task_failed(task, full_error)
        return TaskResult(
            task_id=task.id,
            status="failed",
            error_trace=full_error,
        )

    async def _cleanup_session(
        self, client: httpx.AsyncClient, session_id: str
    ) -> None:
        try:
            await client.delete(f"{OPENCODE_BASE_URL}/session/{session_id}")
        except Exception as e:
            print(f"[CodeAgent] 清理 session 失败: {e}")

    def _build_prompt(self, task: Task) -> str:
        return f"""任务意图：{task.intent}

工作目录：{task.metadata.get("working_dir", ".")}

约束条件：
{task.metadata.get("constraints", "无特殊约束")}

请完成上述任务，并以 JSON 格式返回执行结果。"""

    async def _get_capability_confidence(self, domain: str) -> float:
        if not self.core_memory_cache:
            return 0.5
        return 0.5


class SSEMultiplexer:
    """
    进程级单例：一个全局 SSE 连接，按 sessionID 分发事件到各 Task 监听器。
    生产环境优化：避免 O(N²) SSE 连接问题。
    """

    _instance: Optional["SSEMultiplexer"] = None

    def __init__(self):
        self._listeners: dict[str, asyncio.Queue] = {}
        self._source_task: Optional[asyncio.Task] = None

    @classmethod
    def get_instance(cls) -> "SSEMultiplexer":
        if cls._instance is None:
            cls._instance = SSEMultiplexer()
        return cls._instance

    async def start(self, client: httpx.AsyncClient) -> None:
        async with aconnect_sse(
            client, "GET", f"{OPENCODE_BASE_URL}/global/event"
        ) as source:
            async for sse in source.aiter_sse():
                data = json.loads(sse.data)
                sid = data.get("sessionID")
                if sid and sid in self._listeners:
                    await self._listeners[sid].put(data)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self._listeners[session_id] = q
        return q

    def unsubscribe(self, session_id: str) -> None:
        self._listeners.pop(session_id, None)
