"""Chat API routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel


router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    text: str
    session_id: str
    user_id: str | None = None


@router.post("/chat")
async def chat(request: Request, payload: ChatRequest) -> dict[str, Any]:
    app_state = request.app.state
    inbound = await app_state.web_platform.normalize_inbound(
        {
            "text": payload.text,
            "session_id": payload.session_id,
            "user_id": payload.user_id,
            "capabilities": ["streaming"],
        }
    )
    await app_state.session_context_store.append_message(
        inbound.user_id,
        inbound.session_id,
        {"role": "user", "content": inbound.text},
    )
    action = await app_state.soul_engine.run(inbound)
    result = await app_state.action_router.route(action, inbound)
    if result is None:
        raise HTTPException(status_code=500, detail="action routing failed")
    await app_state.session_context_store.append_message(
        inbound.user_id,
        inbound.session_id,
        {"role": "assistant", "content": result["reply"]},
    )
    return result


@router.get("/chat/stream")
async def chat_stream(request: Request, session_id: str) -> StreamingResponse:
    app_state = request.app.state
    if app_state.streaming_disabled:
        raise HTTPException(status_code=503, detail="streaming unavailable")

    queue = app_state.web_platform.subscribe(session_id)

    async def event_generator():
        try:
            while True:
                item = await queue.get()
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
                if item["event"] == "done":
                    break
        finally:
            app_state.web_platform.unsubscribe(session_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
