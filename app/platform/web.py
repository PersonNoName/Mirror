"""Web platform adapter with in-memory SSE fan-out."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from typing import Any

from app.platform.base import HitlRequest, InboundMessage, OutboundMessage, PlatformAdapter, PlatformContext


class WebPlatformAdapter(PlatformAdapter):
    """Platform adapter for HTTP and SSE-based web clients."""

    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
        self._contexts: dict[str, PlatformContext] = {}
        self._latest_session_by_user: dict[str, str] = {}

    async def normalize_inbound(self, raw_event: Any) -> InboundMessage:
        data = dict(raw_event)
        session_id = data["session_id"]
        user_id = data.get("user_id") or session_id
        capabilities = set(data.get("capabilities", []))
        text = self._normalize_text(data["text"])
        platform_ctx = self.register_session(
            user_id=user_id,
            session_id=session_id,
            capabilities=capabilities,
        )
        return InboundMessage(
            text=text,
            user_id=user_id,
            session_id=session_id,
            platform_ctx=platform_ctx,
            metadata=data.get("metadata", {}),
        )

    async def send_outbound(self, ctx: PlatformContext, message: OutboundMessage) -> None:
        if message.type == "stream":
            await self._broadcast(
                ctx.session_id,
                {"event": "delta", "data": {"delta": str(message.content)}},
            )
            return

        payload = {
            "type": message.type,
            "content": message.content,
            "metadata": message.metadata,
        }
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
            self._drop_session(session_id)

    async def emit_error(self, session_id: str, message: str) -> None:
        await self._broadcast(session_id, {"event": "error", "data": {"message": message}})

    def register_session(
        self,
        *,
        user_id: str,
        session_id: str,
        capabilities: set[str] | None = None,
    ) -> PlatformContext:
        existing = self._contexts.get(session_id)
        if existing is not None:
            if capabilities:
                existing.capabilities.update(capabilities)
            self._latest_session_by_user[user_id] = session_id
            return existing
        ctx = PlatformContext(
            platform="web",
            user_id=user_id,
            session_id=session_id,
            capabilities=set(capabilities or set()),
        )
        self._contexts[session_id] = ctx
        self._latest_session_by_user[user_id] = session_id
        return ctx

    def resolve_context_for_user(self, user_id: str) -> PlatformContext | None:
        session_id = self._latest_session_by_user.get(user_id)
        if not session_id or session_id not in self._queues:
            return None
        return self._contexts.get(session_id)

    def connected_contexts(self) -> list[PlatformContext]:
        return [
            ctx
            for session_id, ctx in self._contexts.items()
            if session_id in self._queues and self._queues[session_id]
        ]

    def _drop_session(self, session_id: str) -> None:
        ctx = self._contexts.pop(session_id, None)
        if ctx is None:
            return
        if self._latest_session_by_user.get(ctx.user_id) == session_id:
            self._latest_session_by_user.pop(ctx.user_id, None)

    async def _broadcast(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._queues.get(session_id, [])):
            await queue.put(event)

    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        text = str(value)
        repaired = cls._repair_utf8_latin1_mojibake(text)
        return repaired if repaired is not None else text

    @staticmethod
    def _repair_utf8_latin1_mojibake(text: str) -> str | None:
        suspicious_markers = ("Ã", "Â", "æ", "ä", "å", "é", "ç", "ð")
        if not any(marker in text for marker in suspicious_markers):
            return None
        try:
            repaired = text.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return None
        original_cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        repaired_cjk = len(re.findall(r"[\u4e00-\u9fff]", repaired))
        if repaired_cjk <= original_cjk:
            return None
        return repaired
