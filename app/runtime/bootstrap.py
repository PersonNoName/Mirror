"""Runtime bootstrap and health snapshot wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import fields
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from app.agents import CodeAgent, WebAgent, agent_registry
from app.config import settings
from app.evolution import (
    CognitionUpdater,
    CoreMemoryScheduler,
    Event,
    EvolutionCandidateManager,
    EvolutionJournal,
    EvolutionScheduler,
    GentleProactivityService,
    MetaCognitionReflector,
    ObserverEngine,
    PersonalityEvolver,
    RelationshipStateMachine,
    RedisStreamsEventBus,
    SignalExtractor,
)
from app.hooks import hook_registry
from app.infra import OutboxStore
from app.memory import (
    CoreMemoryCache,
    CoreMemoryStore,
    GraphStore,
    MemoryGovernanceService,
    SessionContextStore,
    VectorRetriever,
)
from app.observability import ChatTraceService
from app.platform.web import WebPlatformAdapter
from app.providers import ModelProviderRegistry, build_routing_from_settings
from app.skills import SkillLoader
from app.soul import ActionRouter, SoulEngine
from app.stability import AsyncCircuitBreaker, IdempotencyStore, PersonalitySnapshotStore
from app.tasks import Blackboard, OutboxRelay, TaskMonitor, TaskStore, TaskSystem, TaskWorker, TaskWorkerManager
from app.tools import tool_registry
from app.tools.builtin_tools import register_builtin_tools
from app.tools.mcp_adapter import MCPToolAdapter


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


@dataclass(slots=True)
class RuntimeContext:
    """Container for fully wired runtime components."""

    redis_client: Redis | None
    model_registry: ModelProviderRegistry
    outbox_store: OutboxStore
    idempotency_store: IdempotencyStore
    core_memory_store: CoreMemoryStore
    core_memory_cache: CoreMemoryCache
    session_context_store: Any
    vector_retriever: VectorRetriever | None
    graph_store: GraphStore | None
    event_bus: RedisStreamsEventBus
    event_bus_event_factory: Any
    core_memory_scheduler: CoreMemoryScheduler
    evolution_journal: EvolutionJournal
    evolution_candidate_manager: EvolutionCandidateManager | None
    relationship_state_machine: RelationshipStateMachine | None
    proactivity_service: GentleProactivityService
    memory_governance_service: MemoryGovernanceService
    personality_evolver: PersonalityEvolver
    observer: ObserverEngine
    reflector: MetaCognitionReflector
    cognition_updater: CognitionUpdater
    evolution_scheduler: EvolutionScheduler
    task_store: TaskStore
    task_system: TaskSystem
    blackboard: Blackboard
    outbox_relay: OutboxRelay
    task_monitor: TaskMonitor
    worker_manager: TaskWorkerManager
    web_platform: WebPlatformAdapter
    soul_engine: SoulEngine
    action_router: ActionRouter
    skill_loader: SkillLoader
    mcp_adapter: MCPToolAdapter
    chat_trace_service: ChatTraceService
    skill_summary: dict[str, Any] = field(default_factory=dict)
    mcp_summary: dict[str, Any] = field(default_factory=dict)
    builtins_summary: dict[str, Any] = field(default_factory=dict)
    startup_degraded_reasons: list[str] = field(default_factory=list)

    def health_snapshot(self) -> dict[str, Any]:
        skill_loaded = len(self.skill_summary.get("loaded", []))
        skill_skipped = len(self.skill_summary.get("skipped", []))
        skill_failed = len(self.skill_summary.get("failed", []))
        mcp_loaded = len(self.mcp_summary.get("loaded", []))
        mcp_skipped = len(self.mcp_summary.get("skipped", []))
        mcp_failed = len(self.mcp_summary.get("failed", []))
        degraded_worker_count = sum(1 for worker in self.worker_manager.workers if worker.degraded)
        subsystems = {
            "app": {"status": "ok"},
            "postgres": {
                "status": "degraded" if self.task_store.degraded else "ok",
                "reason": "postgres_unavailable" if self.task_store.degraded else None,
            },
            "redis": {
                "status": "degraded" if self.redis_client is None else "ok",
                "reason": "redis_unavailable" if self.redis_client is None else None,
            },
            "neo4j": {
                "status": "degraded" if self.graph_store is None else "ok",
                "reason": "neo4j_unavailable" if self.graph_store is None else None,
            },
            "qdrant": {
                "status": "degraded" if self.vector_retriever is None else "ok",
                "reason": "qdrant_unavailable" if self.vector_retriever is None else None,
            },
            "event_bus": {"status": "degraded" if self.event_bus.degraded else "ok"},
            "outbox_relay": {
                "status": "degraded" if self.outbox_relay.degraded else "ok",
                "reason": "redis_unavailable" if self.outbox_relay.degraded else None,
            },
            "session_context": {
                "status": "degraded" if isinstance(self.session_context_store, _NullSessionContextStore) else "ok",
                "reason": "redis_unavailable" if isinstance(self.session_context_store, _NullSessionContextStore) else None,
            },
            "worker_manager": {
                "status": "degraded" if degraded_worker_count else "ok",
                "workers": len(self.worker_manager.workers),
                "degraded_workers": degraded_worker_count,
            },
            "scheduler": {"status": "ok" if self.evolution_scheduler._task is not None else "degraded"},
            "skill_loader": {
                "status": "ok" if not skill_failed else "degraded",
                "summary": self.skill_summary,
                "loaded_count": skill_loaded,
                "skipped_count": skill_skipped,
                "failed_count": skill_failed,
            },
            "mcp_loader": {
                "status": "ok" if not mcp_failed else "degraded",
                "summary": self.mcp_summary,
                "loaded_count": mcp_loaded,
                "skipped_count": mcp_skipped,
                "failed_count": mcp_failed,
            },
            "evolution_pipeline": self.evolution_candidate_manager.summary()
            if self.evolution_candidate_manager is not None
            else {
                "pending_candidate_count": 0,
                "high_risk_pending_count": 0,
                "recent_reverted_count": 0,
                "degraded": True,
                "status": "degraded",
            },
            "relationship_stage": {
                "relationship_stage_enabled": self.relationship_state_machine is not None,
                "relationship_stage_degraded": self.relationship_state_machine is None
                or self.relationship_state_machine.degraded,
                "status": (
                    "degraded"
                    if self.relationship_state_machine is None or self.relationship_state_machine.degraded
                    else "ok"
                ),
            },
            "memory_governance": {
                "memory_governance_enabled": self.memory_governance_service is not None,
                "memory_governance_degraded": self.memory_governance_service.degraded,
                "status": "degraded" if self.memory_governance_service.degraded else "ok",
            },
            "gentle_proactivity": self.proactivity_service.summary(),
        }
        if "status" not in subsystems["evolution_pipeline"]:
            subsystems["evolution_pipeline"]["status"] = (
                "degraded" if subsystems["evolution_pipeline"]["degraded"] else "ok"
            )
        top_level = "ok"
        if any(item["status"] == "degraded" for item in subsystems.values()):
            top_level = "degraded"
        return {
            "status": top_level,
            "streaming_available": self.redis_client is not None,
            "subsystems": subsystems,
            "startup_degraded_reasons": list(self.startup_degraded_reasons),
        }


async def bootstrap_runtime() -> RuntimeContext:
    """Create a fully wired runtime following the documented startup order."""

    redis_client: Redis | None = None
    startup_degraded_reasons: list[str] = []
    task_store = TaskStore()
    await task_store.initialize()
    if task_store.degraded:
        logger.warning("task_store_degraded", reason="postgres_unavailable")
        startup_degraded_reasons.append("postgres_unavailable")

    outbox_store = OutboxStore()
    await outbox_store.initialize()

    idempotency_store = IdempotencyStore()
    await idempotency_store.initialize()

    evolution_journal = EvolutionJournal()
    await evolution_journal.initialize()
    evolution_candidate_manager: EvolutionCandidateManager | None = None
    try:
        evolution_candidate_manager = EvolutionCandidateManager(evolution_journal)
    except Exception:
        logger.warning("evolution_candidate_manager_degraded", reason="pipeline_initialization_failed")
        startup_degraded_reasons.append("evolution_pipeline_unavailable")

    try:
        redis_client = Redis.from_url(settings.redis.url)
        await redis_client.ping()
    except Exception:
        redis_client = None
        logger.warning("redis_degraded", reason="redis_unavailable")
        startup_degraded_reasons.append("redis_unavailable")

    model_registry = ModelProviderRegistry(build_routing_from_settings(settings))
    core_memory_store = CoreMemoryStore()
    core_memory_cache = CoreMemoryCache(store=core_memory_store, redis_client=redis_client)
    session_context_store = SessionContextStore(redis_client) if redis_client is not None else _NullSessionContextStore()

    graph_store = None
    try:
        graph_store = GraphStore()
    except Exception:
        logger.warning("graph_store_degraded", reason="neo4j_unavailable")
        startup_degraded_reasons.append("neo4j_unavailable")

    vector_retriever = None
    try:
        vector_retriever = VectorRetriever(
            model_registry=model_registry,
            core_memory_cache=core_memory_cache,
        )
    except Exception:
        logger.warning("vector_retriever_degraded", reason="qdrant_unavailable")
        startup_degraded_reasons.append("qdrant_unavailable")

    if startup_degraded_reasons:
        logger.warning(
            "runtime_startup_degraded",
            reasons=startup_degraded_reasons,
        )

    event_bus = RedisStreamsEventBus(
        redis_client=redis_client,
        outbox_store=outbox_store,
        idempotency_store=idempotency_store,
    )
    task_system = TaskSystem(task_store=task_store, outbox_store=outbox_store, redis_client=redis_client)
    blackboard = Blackboard(
        task_store=task_store,
        task_system=task_system,
        agent_registry=agent_registry,
        event_bus=event_bus,
    )
    outbox_relay = OutboxRelay(outbox_store=outbox_store, redis_client=redis_client)
    task_monitor = TaskMonitor(task_store=task_store, blackboard=blackboard)

    web_platform = WebPlatformAdapter()
    chat_trace_service = ChatTraceService(emitter=web_platform.emit_trace)
    circuit_breaker = AsyncCircuitBreaker()
    memory_governance_service = MemoryGovernanceService(
        core_memory_cache=core_memory_cache,
        core_memory_scheduler=None,
        graph_store=graph_store,
        candidate_manager=evolution_candidate_manager,
        evolution_journal=evolution_journal,
    )
    proactivity_service = GentleProactivityService(
        core_memory_cache=core_memory_cache,
        core_memory_scheduler=None,
        evolution_journal=evolution_journal,
    )
    core_memory_scheduler = CoreMemoryScheduler(
        core_memory_store=core_memory_store,
        core_memory_cache=core_memory_cache,
        graph_store=graph_store,
        model_registry=model_registry,
        memory_governance_service=memory_governance_service,
        circuit_breaker=circuit_breaker,
    )
    memory_governance_service.core_memory_scheduler = core_memory_scheduler
    proactivity_service.core_memory_scheduler = core_memory_scheduler
    snapshot_store = PersonalitySnapshotStore()
    personality_evolver = PersonalityEvolver(
        session_context_store=session_context_store,
        core_memory_cache=core_memory_cache,
        core_memory_scheduler=core_memory_scheduler,
        evolution_journal=evolution_journal,
        snapshot_store=snapshot_store,
        candidate_manager=evolution_candidate_manager,
        task_store=task_store,
        blackboard=blackboard,
    )
    relationship_state_machine = (
        RelationshipStateMachine(
            core_memory_cache=core_memory_cache,
            core_memory_scheduler=core_memory_scheduler,
            candidate_manager=evolution_candidate_manager,
            evolution_journal=evolution_journal,
            personality_evolver=personality_evolver,
        )
        if evolution_candidate_manager is not None
        else None
    )
    signal_extractor = SignalExtractor(
        personality_evolver=personality_evolver,
        event_bus=event_bus,
        model_registry=model_registry,
        circuit_breaker=circuit_breaker,
    )
    observer = ObserverEngine(
        model_registry=model_registry,
        graph_store=graph_store,
        vector_retriever=vector_retriever,
        event_bus=event_bus,
    )
    observer.circuit_breaker = circuit_breaker
    reflector = MetaCognitionReflector(
        model_registry=model_registry,
        task_store=task_store,
        event_bus=event_bus,
    )
    reflector.circuit_breaker = circuit_breaker
    cognition_updater = CognitionUpdater(
        core_memory_cache=core_memory_cache,
        core_memory_scheduler=core_memory_scheduler,
        graph_store=graph_store,
        task_store=task_store,
        blackboard=blackboard,
        candidate_manager=evolution_candidate_manager,
        relationship_state_machine=relationship_state_machine,
        memory_governance_service=memory_governance_service,
    )
    scheduler = EvolutionScheduler(
        core_memory_scheduler=core_memory_scheduler,
        graph_store=graph_store,
    )

    builtins = register_builtin_tools(tool_registry)

    soul_engine = SoulEngine(
        model_registry=model_registry,
        core_memory_cache=core_memory_cache,
        session_context_store=session_context_store,
        vector_retriever=vector_retriever,
        tool_registry=tool_registry,
        hook_registry=hook_registry,
        proactivity_service=proactivity_service,
        trace_service=chat_trace_service,
    )
    action_router = ActionRouter(
        platform_adapter=web_platform,
        event_bus=event_bus,
        blackboard=blackboard,
        task_system=task_system,
        tool_registry=tool_registry,
        hook_registry=hook_registry,
        trace_service=chat_trace_service,
    )

    await event_bus.subscribe("dialogue_ended", observer.handle_dialogue_ended)
    await event_bus.subscribe("dialogue_ended", signal_extractor.handle_dialogue_ended)
    await event_bus.subscribe("dialogue_ended", proactivity_service.handle_dialogue_ended)
    await event_bus.subscribe("task_completed", reflector.handle_task_completed)
    await event_bus.subscribe("task_failed", reflector.handle_task_failed)
    await event_bus.subscribe("lesson_generated", cognition_updater.handle_lesson_generated)
    if hasattr(cognition_updater, "handle_hitl_feedback"):
        await event_bus.subscribe("hitl_feedback", cognition_updater.handle_hitl_feedback)
    if hasattr(personality_evolver, "handle_hitl_feedback"):
        await event_bus.subscribe("hitl_feedback", personality_evolver.handle_hitl_feedback)

    agent_registry.register(
        CodeAgent(task_store=task_store, blackboard=blackboard, task_system=task_system),
        source="builtin",
    )
    agent_registry.register(
        WebAgent(task_store=task_store),
        source="builtin",
    )

    skill_loader = SkillLoader(
        skills_dir=settings.SKILLS_DIR,
        tool_registry=tool_registry,
        hook_registry=hook_registry,
        agent_registry=agent_registry,
    )
    skill_summary = skill_loader.load_all()

    mcp_adapter = MCPToolAdapter(
        tool_registry=tool_registry,
        servers_file=settings.MCP_SERVERS_FILE,
        servers_json=settings.MCP_SERVERS_JSON,
    )
    mcp_summary = await mcp_adapter.load_all()

    worker_manager = TaskWorkerManager(
        [
            TaskWorker(
                agent=agent,
                task_store=task_store,
                task_system=task_system,
                blackboard=blackboard,
                platform_adapter=web_platform,
            )
            for agent in agent_registry.all()
        ]
    )

    return RuntimeContext(
        redis_client=redis_client,
        model_registry=model_registry,
        outbox_store=outbox_store,
        idempotency_store=idempotency_store,
        core_memory_store=core_memory_store,
        core_memory_cache=core_memory_cache,
        session_context_store=session_context_store,
        vector_retriever=vector_retriever,
        graph_store=graph_store,
        event_bus=event_bus,
        event_bus_event_factory=lambda event_type, payload: Event(type=event_type, payload=payload),
        core_memory_scheduler=core_memory_scheduler,
        evolution_journal=evolution_journal,
        evolution_candidate_manager=evolution_candidate_manager,
        relationship_state_machine=relationship_state_machine,
        proactivity_service=proactivity_service,
        memory_governance_service=memory_governance_service,
        personality_evolver=personality_evolver,
        observer=observer,
        reflector=reflector,
        cognition_updater=cognition_updater,
        evolution_scheduler=scheduler,
        task_store=task_store,
        task_system=task_system,
        blackboard=blackboard,
        outbox_relay=outbox_relay,
        task_monitor=task_monitor,
        worker_manager=worker_manager,
        web_platform=web_platform,
        soul_engine=soul_engine,
        action_router=action_router,
        skill_loader=skill_loader,
        mcp_adapter=mcp_adapter,
        chat_trace_service=chat_trace_service,
        skill_summary=skill_summary,
        mcp_summary=mcp_summary,
        builtins_summary={"loaded": builtins},
        startup_degraded_reasons=startup_degraded_reasons,
    )


async def start_runtime(runtime: RuntimeContext) -> None:
    runtime.outbox_relay.start()
    runtime.task_monitor.start()
    runtime.worker_manager.start()
    await runtime.event_bus.start()
    runtime.evolution_scheduler.start()


async def stop_runtime(runtime: RuntimeContext) -> None:
    await runtime.evolution_scheduler.stop()
    await runtime.event_bus.stop()
    await runtime.worker_manager.stop()
    await runtime.outbox_relay.stop()
    await runtime.task_monitor.stop()
    if runtime.redis_client is not None:
        await runtime.redis_client.aclose()


def bind_runtime_state(app: FastAPI, runtime: RuntimeContext) -> None:
    """Mirror the runtime context onto FastAPI state for route handlers."""

    app.state.streaming_disabled = runtime.redis_client is None
    for field_info in fields(runtime):
        setattr(app.state, field_info.name, getattr(runtime, field_info.name))
    app.state.runtime = runtime
    app.state.runtime_health = runtime.health_snapshot


@asynccontextmanager
async def runtime_lifespan(app: FastAPI):
    logger.info(
        "app_startup",
        app_name=settings.app.name,
        environment=settings.app.env,
    )
    runtime = await bootstrap_runtime()
    bind_runtime_state(app, runtime)
    await start_runtime(runtime)
    try:
        yield
    finally:
        await stop_runtime(runtime)
        logger.info("app_shutdown", app_name=settings.app.name)
