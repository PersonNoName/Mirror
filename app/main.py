"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from app.agents import agent_registry
from app.api import chat_router, hitl_router
from app.config import settings
from app.evolution import InMemoryEventBus
from app.logging import configure_logging
from app.memory import CoreMemoryCache, CoreMemoryStore, SessionContextStore, VectorRetriever
from app.platform.web import WebPlatformAdapter
from app.providers import ModelProviderRegistry, build_routing_from_settings
from app.soul import ActionRouter, SoulEngine
from app.tasks import Blackboard, OutboxRelay, TaskMonitor, TaskStore, TaskSystem
from app.tools import tool_registry


configure_logging(settings.app.log_level)
logger = structlog.get_logger(__name__)


class _NullSessionContextStore:
    async def append_message(self, *args, **kwargs) -> None:
        return None

    async def get_recent_messages(self, *args, **kwargs):
        return []

    async def set_adaptations(self, *args, **kwargs) -> None:
        return None

    async def get_adaptations(self, *args, **kwargs):
        return []

    async def clear_session(self, *args, **kwargs) -> None:
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "app_startup",
        app_name=settings.app.name,
        environment=settings.app.env,
    )

    redis_client: Redis | None = None
    task_store = TaskStore()
    await task_store.initialize()
    if task_store.degraded:
        logger.warning("task_store_degraded", reason="postgres_unavailable")

    try:
        redis_client = Redis.from_url(settings.redis.url)
        await redis_client.ping()
        app.state.streaming_disabled = False
    except Exception:
        redis_client = None
        app.state.streaming_disabled = False
        logger.warning("redis_degraded", reason="redis_unavailable")

    core_memory_store = CoreMemoryStore()
    core_memory_cache = CoreMemoryCache(store=core_memory_store, redis_client=redis_client)
    session_context_store = SessionContextStore(redis_client) if redis_client is not None else _NullSessionContextStore()
    model_registry = ModelProviderRegistry(build_routing_from_settings(settings))
    web_platform = WebPlatformAdapter()
    event_bus = InMemoryEventBus()
    task_system = TaskSystem(task_store=task_store, redis_client=redis_client)
    blackboard = Blackboard(
        task_store=task_store,
        task_system=task_system,
        agent_registry=agent_registry,
        event_bus=event_bus,
    )
    outbox_relay = OutboxRelay(task_system=task_system, redis_client=redis_client)
    task_monitor = TaskMonitor(task_store=task_store, blackboard=blackboard)

    vector_retriever = None
    try:
        vector_retriever = VectorRetriever(
            model_registry=model_registry,
            core_memory_cache=core_memory_cache,
        )
    except Exception:
        logger.warning("vector_retriever_degraded", reason="qdrant_unavailable")

    soul_engine = SoulEngine(
        model_registry=model_registry,
        core_memory_cache=core_memory_cache,
        session_context_store=session_context_store,
        vector_retriever=vector_retriever,
        tool_registry=tool_registry,
    )
    action_router = ActionRouter(
        platform_adapter=web_platform,
        event_bus=event_bus,
        blackboard=blackboard,
        task_system=task_system,
    )

    app.state.model_registry = model_registry
    app.state.core_memory_store = core_memory_store
    app.state.core_memory_cache = core_memory_cache
    app.state.session_context_store = session_context_store
    app.state.vector_retriever = vector_retriever
    app.state.event_bus = event_bus
    app.state.task_store = task_store
    app.state.task_system = task_system
    app.state.blackboard = blackboard
    app.state.outbox_relay = outbox_relay
    app.state.task_monitor = task_monitor
    app.state.web_platform = web_platform
    app.state.soul_engine = soul_engine
    app.state.action_router = action_router

    outbox_relay.start()
    task_monitor.start()
    try:
        yield
    finally:
        await outbox_relay.stop()
        await task_monitor.stop()
        if redis_client is not None:
            await redis_client.aclose()
        logger.info("app_shutdown", app_name=settings.app.name)


app = FastAPI(title=settings.app.name, lifespan=lifespan)
app.include_router(chat_router)
app.include_router(hitl_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
