"""User memory governance API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.models import (
    ApiErrorResponse,
    ConversationEpisodeItemResponse,
    ConversationEpisodeListResponse,
    MemoryCorrectionRequest,
    MemoryCorrectionResponse,
    MemoryDeleteRequest,
    MemoryDeleteResponse,
    MemoryGovernanceBlockRequest,
    MemoryGovernanceBlockResponse,
    MemoryGovernancePolicyResponse,
    MemoryItemResponse,
    MemoryListResponse,
    MidTermMemoryListResponse,
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
    include_mid_term: bool = Query(default=False),
) -> MemoryListResponse:
    service = request.app.state.memory_governance_service
    items = await service.list_memory(
        user_id=user_id,
        include_candidates=include_candidates,
        include_superseded=include_superseded,
        include_mid_term=include_mid_term,
    )
    return MemoryListResponse(items=[MemoryItemResponse(**item) for item in items], count=len(items))


@router.get("/memory/mid-term", response_model=MidTermMemoryListResponse)
async def list_mid_term_memory(
    request: Request,
    user_id: str = Query(min_length=1),
    include_expired: bool = Query(default=False),
) -> MidTermMemoryListResponse:
    items = await request.app.state.memory_governance_service.list_memory(
        user_id=user_id,
        include_candidates=False,
        include_superseded=include_expired,
        include_mid_term=True,
    )
    filtered = [item for item in items if item.get("visibility") == "mid_term"]
    store = request.app.state.mid_term_memory_store
    return MidTermMemoryListResponse(
        items=[MemoryItemResponse(**item) for item in filtered],
        count=len(filtered),
        degraded=bool(getattr(store, "degraded", False)),
        source=str(getattr(store, "storage_source", "postgres")),
    )


@router.get("/memory/conversation-episodes", response_model=ConversationEpisodeListResponse)
async def list_conversation_episodes(
    request: Request,
    user_id: str = Query(min_length=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> ConversationEpisodeListResponse:
    retriever = getattr(request.app.state, "vector_retriever", None)
    if retriever is None:
        return ConversationEpisodeListResponse(
            items=[],
            count=0,
            degraded=True,
            source="unavailable",
            error="vector_retriever_unavailable",
        )
    items = await retriever.list_namespace_items(
        user_id=user_id,
        namespace="conversation_episode",
        limit=limit,
    )
    error = None
    degraded = False
    last_error = getattr(retriever, "last_namespace_list_error", None)
    if callable(last_error):
        error = last_error(user_id=user_id, namespace="conversation_episode")
        degraded = error is not None
    return ConversationEpisodeListResponse(
        items=[ConversationEpisodeItemResponse(**item) for item in items],
        count=len(items),
        degraded=degraded,
        source="qdrant",
        error=error,
    )


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


@router.post(
    "/memory/mid-term/delete",
    response_model=MemoryDeleteResponse,
    responses={404: {"model": ApiErrorResponse}},
)
async def delete_mid_term_memory(request: Request, payload: MemoryDeleteRequest):
    try:
        await request.app.state.memory_governance_service.delete_mid_term_memory(
            user_id=payload.user_id,
            memory_key=payload.memory_key,
            reason=payload.reason,
        )
    except KeyError:
        return api_error_response(
            status_code=404,
            code="memory_not_found",
            message="No mid-term memory exists for the provided memory_key.",
            details={"memory_key": payload.memory_key},
        )
    return MemoryDeleteResponse(status="ok", memory_key=payload.memory_key)
