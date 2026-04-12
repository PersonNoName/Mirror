"""Chat trace collection for frontend flow visualization."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from uuid import uuid4


TraceEmitter = Callable[[str, dict[str, Any]], Awaitable[None]]


class ChatTraceService:
    """Collect per-session chat traces and optionally emit live updates."""

    def __init__(self, emitter: TraceEmitter | None = None) -> None:
        self._latest_by_session: dict[str, dict[str, Any]] = {}
        self._emitter = emitter

    async def start_trace(self, *, user_id: str, session_id: str, text: str) -> dict[str, Any]:
        trace = {
            "trace_id": str(uuid4()),
            "user_id": user_id,
            "session_id": session_id,
            "status": "running",
            "input": {"text": text},
            "started_at": self._now(),
            "finished_at": None,
            "steps": [],
        }
        self._latest_by_session[session_id] = trace
        await self._emit(session_id)
        return deepcopy(trace)

    async def add_step(
        self,
        session_id: str,
        *,
        step_type: str,
        title: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        trace = self._latest_by_session.get(session_id)
        if trace is None:
            return
        trace["steps"].append(
            {
                "id": str(uuid4()),
                "type": step_type,
                "title": title,
                "data": data or {},
                "created_at": self._now(),
            }
        )
        await self._emit(session_id)

    async def finish_trace(
        self,
        session_id: str,
        *,
        status: str,
        output: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        trace = self._latest_by_session.get(session_id)
        if trace is None:
            return None
        trace["status"] = status
        trace["finished_at"] = self._now()
        if output is not None:
            trace["output"] = output
        await self._emit(session_id)
        return deepcopy(trace)

    def get_latest(self, session_id: str) -> dict[str, Any] | None:
        trace = self._latest_by_session.get(session_id)
        if trace is None:
            return None
        return deepcopy(trace)

    async def _emit(self, session_id: str) -> None:
        if self._emitter is None:
            return
        trace = self._latest_by_session.get(session_id)
        if trace is None:
            return
        await self._emitter(session_id, deepcopy(trace))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
