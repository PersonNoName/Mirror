from __future__ import annotations

import pytest

import app.runtime.bootstrap as bootstrap_module


class StubTaskStore:
    def __init__(self) -> None:
        self.degraded = True

    async def initialize(self) -> None:
        return None


class StubOutboxStore:
    def __init__(self) -> None:
        self.degraded = True

    async def initialize(self) -> None:
        return None


class StubIdempotencyStore:
    async def initialize(self) -> None:
        return None


class StubEvolutionJournal:
    async def initialize(self) -> None:
        return None


class StubModelRegistry:
    def __init__(self, specs: dict[str, object]) -> None:
        self.specs = specs


class StubCoreMemoryStore:
    pass


class StubBlackboard:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class StubOutboxRelay:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.degraded = kwargs.get("redis_client") is None

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class StubTaskMonitor:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class StubWebPlatformAdapter:
    pass


class StubCoreMemoryScheduler:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class StubSnapshotStore:
    pass


class StubPersonalityEvolver:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class StubRelationshipStateMachine:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.degraded = False


class StubSignalExtractor:
    def __init__(self, personality_evolver: object, event_bus: object | None = None) -> None:
        self.personality_evolver = personality_evolver
        self.event_bus = event_bus

    async def handle_dialogue_ended(self, event: object) -> None:
        return None


class StubObserver:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.circuit_breaker = None

    async def handle_dialogue_ended(self, event: object) -> None:
        return None


class StubReflector:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.circuit_breaker = None

    async def handle_task_completed(self, event: object) -> None:
        return None

    async def handle_task_failed(self, event: object) -> None:
        return None


class StubCognitionUpdater:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def handle_lesson_generated(self, event: object) -> None:
        return None


class StubScheduler:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self._task = None

    def start(self) -> None:
        self._task = object()

    async def stop(self) -> None:
        self._task = None


class StubSkillLoader:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def load_all(self) -> dict[str, list[object]]:
        return {"loaded": [], "skipped": [], "failed": []}


class StubMCPAdapter:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    async def load_all(self) -> dict[str, list[object]]:
        return {"loaded": [], "skipped": [], "failed": []}


class StubTaskWorker:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.degraded = kwargs["task_system"].redis_client is None


class StubTaskWorkerManager:
    def __init__(self, workers: list[object]) -> None:
        self.workers = workers

    def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class StubAgent:
    def __init__(self, name: str) -> None:
        self.name = name


class StubAgentRegistry:
    def __init__(self) -> None:
        self._agents: list[object] = []

    def register(self, agent: object, source: str = "builtin", overwrite: bool = True, metadata: dict | None = None) -> None:
        self._agents.append(agent)

    def all(self) -> list[object]:
        return list(self._agents)


class StubEventBus:
    def __init__(self, redis_client: object, outbox_store: object, idempotency_store: object | None = None) -> None:
        self.redis_client = redis_client
        self.outbox_store = outbox_store
        self.idempotency_store = idempotency_store
        self.degraded = redis_client is None
        self.subscriptions: list[tuple[str, object]] = []

    async def subscribe(self, event_type: str, handler: object) -> None:
        self.subscriptions.append((event_type, handler))

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


@pytest.mark.asyncio
async def test_bootstrap_runtime_survives_degraded_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap_module, "TaskStore", StubTaskStore)
    monkeypatch.setattr(bootstrap_module, "OutboxStore", StubOutboxStore)
    monkeypatch.setattr(bootstrap_module, "IdempotencyStore", StubIdempotencyStore)
    monkeypatch.setattr(bootstrap_module, "EvolutionJournal", StubEvolutionJournal)
    monkeypatch.setattr(bootstrap_module, "ModelProviderRegistry", StubModelRegistry)
    monkeypatch.setattr(bootstrap_module, "build_routing_from_settings", lambda settings: {})
    monkeypatch.setattr(bootstrap_module, "CoreMemoryStore", StubCoreMemoryStore)
    monkeypatch.setattr(bootstrap_module, "Blackboard", StubBlackboard)
    monkeypatch.setattr(bootstrap_module, "OutboxRelay", StubOutboxRelay)
    monkeypatch.setattr(bootstrap_module, "TaskMonitor", StubTaskMonitor)
    monkeypatch.setattr(bootstrap_module, "WebPlatformAdapter", StubWebPlatformAdapter)
    monkeypatch.setattr(bootstrap_module, "AsyncCircuitBreaker", lambda: object())
    monkeypatch.setattr(bootstrap_module, "CoreMemoryScheduler", StubCoreMemoryScheduler)
    monkeypatch.setattr(bootstrap_module, "PersonalitySnapshotStore", StubSnapshotStore)
    monkeypatch.setattr(bootstrap_module, "PersonalityEvolver", StubPersonalityEvolver)
    monkeypatch.setattr(bootstrap_module, "RelationshipStateMachine", StubRelationshipStateMachine)
    monkeypatch.setattr(bootstrap_module, "SignalExtractor", StubSignalExtractor)
    monkeypatch.setattr(bootstrap_module, "ObserverEngine", StubObserver)
    monkeypatch.setattr(bootstrap_module, "MetaCognitionReflector", StubReflector)
    monkeypatch.setattr(bootstrap_module, "CognitionUpdater", StubCognitionUpdater)
    monkeypatch.setattr(bootstrap_module, "EvolutionScheduler", StubScheduler)
    monkeypatch.setattr(bootstrap_module, "register_builtin_tools", lambda registry: ["echo"])
    monkeypatch.setattr(bootstrap_module, "SkillLoader", StubSkillLoader)
    monkeypatch.setattr(bootstrap_module, "MCPToolAdapter", StubMCPAdapter)
    monkeypatch.setattr(bootstrap_module, "TaskWorker", StubTaskWorker)
    monkeypatch.setattr(bootstrap_module, "TaskWorkerManager", StubTaskWorkerManager)
    monkeypatch.setattr(bootstrap_module, "RedisStreamsEventBus", StubEventBus)
    monkeypatch.setattr(bootstrap_module, "CodeAgent", lambda **kwargs: StubAgent("code_agent"))
    monkeypatch.setattr(bootstrap_module, "WebAgent", lambda **kwargs: StubAgent("web_agent"))
    monkeypatch.setattr(bootstrap_module, "agent_registry", StubAgentRegistry())

    class RedisStub:
        @staticmethod
        def from_url(url: str) -> object:
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(bootstrap_module, "Redis", RedisStub)
    monkeypatch.setattr(bootstrap_module, "GraphStore", lambda: (_ for _ in ()).throw(RuntimeError("neo4j unavailable")))
    monkeypatch.setattr(
        bootstrap_module,
        "VectorRetriever",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("qdrant unavailable")),
    )

    runtime = await bootstrap_module.bootstrap_runtime()
    health = runtime.health_snapshot()

    assert runtime.redis_client is None
    assert runtime.graph_store is None
    assert runtime.vector_retriever is None
    assert health["status"] == "degraded"
    assert health["subsystems"]["redis"]["status"] == "degraded"
    assert health["subsystems"]["neo4j"]["status"] == "degraded"
    assert health["subsystems"]["qdrant"]["status"] == "degraded"
    assert health["subsystems"]["evolution_pipeline"]["status"] == "ok"
    assert health["subsystems"]["evolution_pipeline"]["pending_candidate_count"] == 0
    assert health["subsystems"]["relationship_stage"]["status"] == "ok"
    assert health["subsystems"]["relationship_stage"]["relationship_stage_enabled"] is True
    assert health["subsystems"]["memory_governance"]["status"] == "ok"
