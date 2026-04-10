"""HITL response API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


router = APIRouter(tags=["hitl"])


class HitlResponseRequest(BaseModel):
    task_id: str
    decision: str = Field(pattern="^(approve|reject)$")
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/hitl/respond")
async def hitl_respond(request: Request, payload: HitlResponseRequest) -> dict[str, Any]:
    task = await request.app.state.blackboard.resume(
        payload.task_id,
        {"decision": payload.decision, "payload": payload.payload},
    )
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    await request.app.state.task_system.register_hitl_response(
        payload.task_id,
        payload.decision,
        payload.payload,
    )
    return {"status": "ok", "task_id": payload.task_id, "decision": payload.decision}
