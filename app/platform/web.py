"""Web platform adapter with in-memory SSE fan-out."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from app.platform.base import HitlRequest, InboundMessage, OutboundMessage, PlatformAdapter, PlatformContext


class WebPlatformAdapter(PlatformAdapter):
    """Platform adapter for HTTP and SSE-based web clients."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)

    async def normalize_inbound(self, raw_event: Any) -> InboundMessage:
        data = dict(raw_event)
        session_id = data["session_id"]
        user_id = data.get("user_id") or session_id
        capabilities = set(data.get("capabilities", []))
        platform_ctx = PlatformContext(
            platform="web",
            user_id=user_id,
            session_id=session_id,
            capabilities=capabilities,
        )
        return InboundMessage(
            text=data["text"],
            user_id=user_id,
            session_id=session_id,
            platform_ctx=platform_ctx,
            metadata=data.get("metadata", {}),
        )

    async def send_outbound(self, ctx: PlatformContext, message: OutboundMessage) -> None:
        payload = {
            "type": message.type,
            "content": message.content,
            "metadata": message.metadata,
        }
        if "streaming" in ctx.capabilities:
            for chunk in self._chunk_text(str(message.content)):
                await self._broadcast(
                    ctx.session_id,
                    {"event": "delta", "data": {"delta": chunk}},
                )
        await self._broadcast(
            ctx.session_id,
            {"event": "message", "data": payload},
        )
        await self._broadcast(ctx.session_id, {"event": "done", "data": {"status": "done"}})

    async def send_hitl(self, ctx: PlatformContext, req: HitlRequest) -> None:
        await self._broadcast(
            ctx.session_id,
            {
                "event": "message",
                "data": {"type": "hitl_request", "content": req.description, "metadata": {"task_id": req.task_id}},
            },
        )
        await self._broadcast(ctx.session_id, {"event": "done", "data": {"status": "waiting_hitl"}})

    async def emit_trace(self, session_id: str, trace: dict[str, Any]) -> None:
        await self._broadcast(session_id, {"event": "trace", "data": trace})

    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues[session_id].append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        listeners = self._queues.get(session_id, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners:
            self._queues.pop(session_id, None)

    async def emit_error(self, session_id: str, message: str) -> None:
        await self._broadcast(session_id, {"event": "error", "data": {"message": message}})

    async def _broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._queues.get(session_id, [])):
            await queue.put(event)

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 32) -> list[str]:
        if not text:
            return [""]
        return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]
