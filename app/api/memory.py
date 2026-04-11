"""User memory governance API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.models import (
    ApiErrorResponse,
    MemoryCorrectionRequest,
    MemoryCorrectionResponse,
    MemoryDeleteRequest,
    MemoryDeleteResponse,
    MemoryGovernanceBlockRequest,
    MemoryGovernanceBlockResponse,
    MemoryGovernancePolicyResponse,
    MemoryItemResponse,
    MemoryListResponse,
    api_error_response,
)


router = APIRouter(tags=["memory"])


@router.get(
    "/memory",
    response_model=MemoryListResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def list_memory(
    request: Request,
    user_id: str = Query(min_length=1),
    include_candidates: bool = Query(default=True),
    include_superseded: bool = Query(default=False),
) -> MemoryListResponse:
    service = request.app.state.memory_governance_service
    items = await service.list_memory(
        user_id=user_id,
        include_candidates=include_candidates,
        include_superseded=include_superseded,
    )
    return MemoryListResponse(items=[MemoryItemResponse(**item) for item in items], count=len(items))


@router.get("/memory/governance", response_model=MemoryGovernancePolicyResponse)
async def get_memory_governance(request: Request, user_id: str = Query(min_length=1)) -> MemoryGovernancePolicyResponse:
    policy = await request.app.state.memory_governance_service.get_policy(user_id)
    return MemoryGovernancePolicyResponse(
        user_id=user_id,
        blocked_content_classes=list(policy.blocked_content_classes),
        retention_days=dict(policy.retention_days),
        updated_at=policy.updated_at,
    )


@router.post(
    "/memory/governance/block",
    response_model=MemoryGovernanceBlockResponse,
)
async def block_memory_learning(
    request: Request,
    payload: MemoryGovernanceBlockRequest,
) -> MemoryGovernanceBlockResponse:
    policy = await request.app.state.memory_governance_service.set_blocked(
        user_id=payload.user_id,
        content_class=payload.content_class,
        blocked=payload.blocked,
    )
    response_policy = MemoryGovernancePolicyResponse(
        user_id=payload.user_id,
        blocked_content_classes=list(policy.blocked_content_classes),
        retention_days=dict(policy.retention_days),
        updated_at=policy.updated_at,
    )
    return MemoryGovernanceBlockResponse(
        user_id=payload.user_id,
        content_class=payload.content_class,
        blocked=payload.blocked,
        policy=response_policy,
    )


@router.post(
    "/memory/correct",
    response_model=MemoryCorrectionResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def correct_memory(request: Request, payload: MemoryCorrectionRequest):
    try:
        item = await request.app.state.memory_governance_service.correct_memory(
            user_id=payload.user_id,
            memory_key=payload.memory_key,
            corrected_content=payload.corrected_content,
            truth_type=payload.truth_type,
            subject=payload.subject,
            relation=payload.relation,
            object=payload.object,
        )
    except KeyError:
        return api_error_response(
            status_code=404,
            code="memory_not_found",
            message="No user-governed memory exists for the provided memory_key.",
            details={"memory_key": payload.memory_key},
        )
    return MemoryCorrectionResponse(status="ok", item=MemoryItemResponse(**item))


@router.post(
    "/memory/delete",
    response_model=MemoryDeleteResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def delete_memory(request: Request, payload: MemoryDeleteRequest):
    try:
        await request.app.state.memory_governance_service.delete_memory(
            user_id=payload.user_id,
            memory_key=payload.memory_key,
            reason=payload.reason,
        )
    except KeyError:
        return api_error_response(
            status_code=404,
            code="memory_not_found",
            message="No user-governed memory exists for the provided memory_key.",
            details={"memory_key": payload.memory_key},
        )
    return MemoryDeleteResponse(status="ok", memory_key=payload.memory_key)
