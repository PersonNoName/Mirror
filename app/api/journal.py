"""Evolution journal API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.models import EvolutionJournalItemResponse, EvolutionJournalResponse

router = APIRouter(tags=["evolution"])


@router.get("/evolution/journal", response_model=EvolutionJournalResponse)
async def evolution_journal(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str | None = Query(default=None),
) -> EvolutionJournalResponse:
    items = await request.app.state.evolution_journal.list_recent(limit=limit, user_id=user_id)
    return EvolutionJournalResponse(
        items=[
            EvolutionJournalItemResponse(
                id=item.id,
                user_id=item.user_id,
                event_type=item.event_type,
                summary=item.summary,
                details=item.details,
                created_at=item.created_at,
            )
            for item in items
        ],
        count=len(items),
    )
