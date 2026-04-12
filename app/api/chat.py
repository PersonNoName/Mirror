"""Chat API routes."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from app.api.models import (
    APIModel,
    ApiErrorResponse,
    ChatBrainResponse,
    ChatMetaResponse,
    ChatResponse,
    ChatTraceResponse,
    NonEmptyStr,
    OptionalNonEmptyStr,
    api_error_response,
)
from app.platform.base import OutboundMessage


router = APIRouter(tags=["chat"])


class ChatRequest(APIModel):
    text: NonEmptyStr
    session_id: NonEmptyStr
    user_id: OptionalNonEmptyStr = None
    include_trace: bool = False


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

    trace = await app_state.chat_trace_service.start_trace(
        user_id=inbound.user_id,
        session_id=inbound.session_id,
        text=inbound.text,
    )
    inbound.metadata["trace_id"] = trace["trace_id"]
    app_state.core_memory_cache.mark_session_active(inbound.user_id, inbound.session_id)
    await app_state.chat_trace_service.add_step(
        inbound.session_id,
        step_type="session",
        title="Session marked active",
        data={"user_id": inbound.user_id, "session_id": inbound.session_id},
    )
    await app_state.session_context_store.append_message(
        inbound.user_id,
        inbound.session_id,
        {"role": "user", "content": inbound.text},
    )
    await app_state.chat_trace_service.add_step(
        inbound.session_id,
        step_type="context",
        title="User message appended to session context",
        data={"role": "user", "content_preview": inbound.text[:200]},
    )
    async def stream_delta(delta: str) -> None:
        if not delta:
            return
        await app_state.web_platform.send_outbound(
            inbound.platform_ctx,
            OutboundMessage(type="stream", content=delta),
        )

    action = await app_state.soul_engine.run(inbound, on_direct_reply_delta=stream_delta)
    result = await app_state.action_router.route(action, inbound)
    if result is None:
        await app_state.chat_trace_service.finish_trace(
            inbound.session_id,
            status="failed",
            output={"error": "action_routing_failed"},
        )
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
    await app_state.chat_trace_service.add_step(
        inbound.session_id,
        step_type="context",
        title="Assistant reply appended to session context",
        data={"role": "assistant", "content_preview": str(result["reply"])[:200]},
    )
    status = _chat_status_from_result(result)
    final_trace = await app_state.chat_trace_service.finish_trace(
        inbound.session_id,
        status=status,
        output={"reply": str(result["reply"]), "action": str(result.get("action", ""))},
    )
    meta = ChatMetaResponse(
        task_id=str(result["task_id"]) if result.get("task_id") else None,
        trace_id=trace["trace_id"],
    )
    return ChatResponse(
        reply=str(result["reply"]),
        session_id=inbound.session_id,
        user_id=inbound.user_id,
        status=status,
        meta=meta,
        trace=ChatTraceResponse.model_validate(final_trace) if payload.include_trace and final_trace else None,
        brain=ChatBrainResponse.model_validate(result["brain"]) if result.get("brain") else None,
    )


@router.get(
    "/chat/stream",
    response_model=None,
    responses={503: {"model": ApiErrorResponse}},
)
async def chat_stream(
    request: Request,
    session_id: Annotated[str, Query(min_length=1)],
    user_id: Annotated[str | None, Query(min_length=1)] = None,
) -> StreamingResponse | Any:
    app_state = request.app.state
    if app_state.streaming_disabled:
        return api_error_response(
            status_code=503,
            code="streaming_unavailable",
            message="Streaming is currently unavailable for this runtime.",
            details={"session_id": session_id},
        )

    if user_id and hasattr(app_state.web_platform, "register_session"):
        app_state.web_platform.register_session(
            user_id=user_id,
            session_id=session_id,
            capabilities={"streaming"},
        )
    queue = app_state.web_platform.subscribe(session_id)
    if user_id and hasattr(app_state, "proactivity_service"):
        ctx = None
        if hasattr(app_state.web_platform, "resolve_context_for_user"):
            ctx = app_state.web_platform.resolve_context_for_user(user_id)
        if ctx is not None:
            await app_state.proactivity_service.deliver_follow_up(
                user_id=user_id,
                ctx=ctx,
                platform_adapter=app_state.web_platform,
            )

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


@router.get(
    "/chat/trace",
    response_model=ChatTraceResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def chat_trace(
    request: Request,
    session_id: Annotated[str, Query(min_length=1)],
) -> ChatTraceResponse | Any:
    trace = request.app.state.chat_trace_service.get_latest(session_id)
    if trace is None:
        return api_error_response(
            status_code=404,
            code="trace_not_found",
            message="No chat trace exists for the provided session_id.",
            details={"session_id": session_id},
        )
    return ChatTraceResponse.model_validate(trace)


def _chat_status_from_result(result: dict[str, Any]) -> str:
    action = str(result.get("action", ""))
    if action == "publish_task":
        return "accepted"
    if action == "hitl_relay":
        return "waiting_hitl"
    return "completed"
