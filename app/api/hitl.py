"""HITL response API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import Field

from app.api.models import APIModel, ApiErrorResponse, HitlResponse, NonEmptyStr, api_error_response


router = APIRouter(tags=["hitl"])


class HitlResponseRequest(APIModel):
    task_id: NonEmptyStr
    decision: str = Field(pattern="^(approve|reject|defer)$")
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post(
    "/hitl/respond",
    response_model=HitlResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def hitl_respond(request: Request, payload: HitlResponseRequest) -> HitlResponse | Any:
    task = await request.app.state.blackboard.resume(
        payload.task_id,
        {"decision": payload.decision, "payload": payload.payload},
    )
    if task is None:
        return api_error_response(
            status_code=404,
            code="task_not_found",
            message="No HITL task exists for the provided task_id.",
            details={"task_id": payload.task_id},
        )
    await request.app.state.task_system.register_hitl_response(
        payload.task_id,
        payload.decision,
        payload.payload,
    )
    await request.app.state.event_bus.emit(
        request.app.state.event_bus_event_factory(
            "hitl_feedback",
            {
                "task_id": payload.task_id,
                "decision": payload.decision,
                "payload": payload.payload,
            },
        )
    )
    return HitlResponse(status="ok", task_id=payload.task_id, decision=payload.decision)
