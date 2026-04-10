"""FastAPI application entry point."""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.config import settings
from app.logging import configure_logging


configure_logging(settings.app.log_level)
logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info(
        "app_startup",
        app_name=settings.app.name,
        environment=settings.app.env,
    )
    try:
        yield
    finally:
        logger.info("app_shutdown", app_name=settings.app.name)


app = FastAPI(title=settings.app.name, lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
