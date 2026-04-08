import asyncio
import uuid
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class HITLRequest:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    message: str = ""
    task_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"
    response: Optional[dict] = None


class HITLGateway:
    """
    HITL (Human-In-The-Loop) 网关：处理需要用户确认的高风险操作。

    支持两种模式：
    1. Webhook 模式：向外部服务发送确认请求
    2. 轮询模式：本地等待用户响应
    """

    DEFAULT_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        default_timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self.webhook_url = webhook_url
        self.webhook_secret = webhook_secret
        self.default_timeout = default_timeout
        self._pending_requests: dict[str, HITLRequest] = {}
        self._response_events: dict[str, asyncio.Event] = {}

    async def ask_user(self, message: str, task_id: Optional[str] = None) -> dict:
        """
        请求用户确认，返回用户响应。
        如果配置了 webhook，通过 webhook 发送确认请求并等待响应。
        否则使用本地轮询模式。
        """
        request = HITLRequest(
            message=message,
            task_id=task_id,
            status="pending",
        )
        self._pending_requests[request.id] = request
        self._response_events[request.id] = asyncio.Event()

        if self.webhook_url:
            return await self._ask_via_webhook(request)
        else:
            return await self._ask_via_local_poll(request)

    async def _ask_via_webhook(self, request: HITLRequest) -> dict:
        import httpx

        headers = {}
        if self.webhook_secret:
            headers["Authorization"] = f"Bearer {self.webhook_secret}"
        headers["Content-Type"] = "application/json"

        payload = {
            "request_id": request.id,
            "message": request.message,
            "task_id": request.task_id,
            "timeout_seconds": self.default_timeout,
        }

        try:
            async with httpx.AsyncClient(timeout=self.default_timeout + 10) as client:
                resp = await client.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                )
                resp.raise_for_status()
                result = resp.json()

                request.status = "responded"
                request.response = result
                return result

        except httpx.TimeoutException:
            request.status = "timeout"
            return {"approved": False, "result": "请求超时"}
        except httpx.HTTPError as e:
            request.status = "error"
            return {"approved": False, "result": f"Webhook error: {e}"}

    async def _ask_via_local_poll(self, request: HITLRequest) -> dict:
        print(f"[HITLGateway] 等待用户确认: {request.message[:80]}...")
        print(f"[HITLGateway] Request ID: {request.id} (请在外部系统处理)")

        try:
            await asyncio.wait_for(
                self._response_events[request.id].wait(),
                timeout=self.default_timeout,
            )
        except asyncio.TimeoutError:
            request.status = "timeout"
            return {"approved": False, "result": "用户确认超时"}

        request.status = "responded"
        return request.response or {"approved": False, "result": "无响应"}

    async def respond(self, request_id: str, approved: bool, result: str = "") -> None:
        """
        外部系统调用此方法提交用户响应。
        """
        if request_id in self._pending_requests:
            request = self._pending_requests[request_id]
            request.response = {"approved": approved, "result": result}
            request.status = "responded"

            if request_id in self._response_events:
                self._response_events[request_id].set()

    def get_pending_requests(self) -> list[HITLRequest]:
        """获取所有待确认的请求"""
        return [
            req for req in self._pending_requests.values() if req.status == "pending"
        ]

    def cancel_request(self, request_id: str) -> bool:
        """取消一个待确认的请求"""
        if request_id in self._pending_requests:
            self._pending_requests[request_id].status = "cancelled"
            if request_id in self._response_events:
                self._response_events[request_id].set()
            return True
        return False
