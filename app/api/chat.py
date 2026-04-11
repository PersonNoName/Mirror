"""Chat API routes."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.models import APIModel, ApiErrorResponse, ChatMetaResponse, ChatResponse, NonEmptyStr, OptionalNonEmptyStr, api_error_response


router = APIRouter(tags=["chat"])


class ChatRequest(APIModel):
    text: NonEmptyStr
    session_id: NonEmptyStr
    user_id: OptionalNonEmptyStr = None


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={500: {"model": ApiErrorResponse}},
)
async def chat(request: Request, payload: ChatRequest) -> ChatResponse | Any:
    app_state = request.app.state
    inbound = await app_state.web_platform.normalize_inbound(
        {
            "text": payload.text,
            "session_id": payload.session_id,
            "user_id": payload.user_id,
            "capabilities": ["streaming"],
        }
    )
    app_state.core_memory_cache.mark_session_active(inbound.user_id, inbound.session_id)
    await app_state.session_context_store.append_message(
        inbound.user_id,
        inbound.session_id,
        {"role": "user", "content": inbound.text},
    )
    action = await app_state.soul_engine.run(inbound)
    result = await app_state.action_router.route(action, inbound)
    if result is None:
        return api_error_response(
            status_code=500,
            code="action_routing_failed",
            message="The action router did not produce a reply.",
            details={"session_id": inbound.session_id},
        )
    await app_state.session_context_store.append_message(
        inbound.user_id,
        inbound.session_id,
        {"role": "assistant", "content": result["reply"]},
    )
    status = _chat_status_from_result(result)
    meta = ChatMetaResponse(task_id=str(result["task_id"])) if result.get("task_id") else None
    return ChatResponse(
        reply=str(result["reply"]),
        session_id=inbound.session_id,
        user_id=inbound.user_id,
        status=status,
        meta=meta,
    )


@router.get(
    "/chat/stream",
    response_model=None,
    responses={503: {"model": ApiErrorResponse}},
)
async def chat_stream(
    request: Request,
    session_id: Annotated[str, Query(min_length=1)],
) -> StreamingResponse | Any:
    app_state = request.app.state
    if app_state.streaming_disabled:
        return api_error_response(
            status_code=503,
            code="streaming_unavailable",
            message="Streaming is currently unavailable for this runtime.",
            details={"session_id": session_id},
        )

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


def _chat_status_from_result(result: dict[str, Any]) -> str:
    action = str(result.get("action", ""))
    if action == "publish_task":
        return "accepted"
    if action == "hitl_relay":
        return "waiting_hitl"
    return "completed"
