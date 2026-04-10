"""Evolution journal API routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request


router = APIRouter(tags=["evolution"])


@router.get("/evolution/journal")
async def evolution_journal(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    user_id: str | None = Query(default=None),
) -> dict[str, object]:
    items = await request.app.state.evolution_journal.list_recent(limit=limit, user_id=user_id)
    return {
        "items": [
            {
                "id": item.id,
                "user_id": item.user_id,
                "event_type": item.event_type,
                "summary": item.summary,
                "details": item.details,
                "created_at": item.created_at.isoformat(),
            }
            for item in items
        ],
        "count": len(items),
    }
