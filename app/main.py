"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from app.api import chat_router, hitl_router, journal_router
from app.config import settings
from app.logging import configure_logging
from app.runtime import runtime_lifespan


configure_logging(settings.app.log_level)

app = FastAPI(title=settings.app.name, lifespan=runtime_lifespan)
app.include_router(chat_router)
app.include_router(hitl_router)
app.include_router(journal_router)


@app.get("/health")
async def health() -> dict[str, object]:
    runtime_health = getattr(app.state, "runtime_health", None)
    if callable(runtime_health):
        return runtime_health()
    return {"status": "starting", "subsystems": {"app": {"status": "starting"}}}
