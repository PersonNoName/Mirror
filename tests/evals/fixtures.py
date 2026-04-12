from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.evolution import (
    CognitionUpdater,
    EvolutionCandidateManager,
    EvolutionEntry,
    EvolutionJournal,
    GentleProactivityService,
    InteractionSignal,
    PersonalityEvolver,
    RelationshipStateMachine,
)
from app.memory import CoreMemory, MemoryGovernanceService
from app.memory.core_memory import BehavioralRule
from app.memory.mid_term_memory import MidTermMemoryStore
from app.platform.base import InboundMessage, PlatformContext
from app.stability.snapshot import PersonalitySnapshotStore
from app.soul import SoulEngine

from tests.conftest import (
    DummyCoreMemoryCache,
    DummyModelRegistry,
    DummySessionContextStore,
    DummyToolCatalog,
    DummyVectorRetriever,
)


@dataclass(slots=True)
class CompanionMetricResult:
    name: str
    score: float
    passed: bool
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CompanionEvalTurn:
    name: str
    session_id: str
    user_text: str
    notes: str = ""


@dataclass(slots=True)
class CompanionEvalResult:
    scenario_id: str
    passed: bool
    metrics: list[CompanionMetricResult]
    failures: list[str] = field(default_factory=list)
    journal_events_checked: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompanionEvalScenario:
    scenario_id: str
    description: str
    turns: list[CompanionEvalTurn]
    runner: Callable[["EvalHarness"], Awaitable[CompanionEvalResult]]


class RecordingJournal(EvolutionJournal):
    def __init__(self) -> None:
        super().__init__(dsn="")
        self.degraded = True
        self.entries: list[EvolutionEntry] = []

    async def record(self, entry: EvolutionEntry) -> None:
        self.entries.append(entry)
        await super().record(entry)


class RecordingGraphStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []
        self.superseded: list[dict[str, Any]] = []

    async def upsert_relation(self, **kwargs: Any) -> None:
        self.upserts.append(dict(kwargs))

    async def supersede_relation(self, **kwargs: Any) -> None:
        self.superseded.append(dict(kwargs))

    async def query_relations_by_user(self, user_id: str, relation_types: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        items = [item for item in self.upserts if item.get("user_id") == user_id]
        if relation_types is not None:
            items = [item for item in items if item.get("relation") in relation_types]
        result: list[dict[str, Any]] = []
        for item in items[:limit]:
            result.append(
                {
                    "subject": item["subject"],
                    "relation": item["relation"],
                    "object": item["object"],
                    "source": item.get("source", "lesson"),
                    "confidence": item.get("confidence", 0.0),
                    "updated_at": item.get("metadata", {}).get("updated_at", "") or item.get("updated_at", ""),
                    "confirmed_by_user": item.get("confirmed_by_user", False),
                    "status": item.get("status", "active"),
                    "time_horizon": item.get("time_horizon", "long_term"),
                    "sensitivity": item.get("sensitivity", "normal"),
                    "conflict_with": item.get("conflict_with", []),
                    "metadata": item.get("metadata", {}),
                }
            )
        return result


class RecordingScheduler:
    def __init__(self, core_memory: CoreMemory) -> None:
        self.core_memory = core_memory
        self.calls: list[tuple[str, str, object, str | None]] = []

    async def write(self, user_id: str, block: str, content: object, event_id: str | None = None) -> CoreMemory:
        clone = deepcopy(content)
        self.calls.append((user_id, block, clone, event_id))
        if block == "world_model":
            self.core_memory.world_model = clone  # type: ignore[assignment]
        elif block == "personality":
            self.core_memory.personality = clone  # type: ignore[assignment]
        elif block == "self_cognition":
            self.core_memory.self_cognition = clone  # type: ignore[assignment]
        return self.core_memory


@dataclass(slots=True)
class EvalHarness:
    core_memory: CoreMemory
    cache: DummyCoreMemoryCache
    session_store: DummySessionContextStore
    vector_retriever: DummyVectorRetriever
    journal: RecordingJournal
    scheduler: RecordingScheduler
    graph_store: RecordingGraphStore
    candidate_manager: EvolutionCandidateManager
    snapshot_store: PersonalitySnapshotStore
    governance_service: MemoryGovernanceService
    personality_evolver: PersonalityEvolver
    relationship_state_machine: RelationshipStateMachine
    proactivity_service: GentleProactivityService
    cognition_updater: CognitionUpdater
    soul_engine: SoulEngine

    def build_message(self, text: str, session_id: str = "session-1") -> InboundMessage:
        ctx = PlatformContext(platform="web", user_id="user-1", session_id=session_id, capabilities={"streaming"})
        return InboundMessage(text=text, user_id="user-1", session_id=session_id, platform_ctx=ctx)

    async def run_soul(self, text: str, session_id: str = "session-1"):
        return await self.soul_engine.run(self.build_message(text, session_id=session_id))

    async def capture_dialogue(self, text: str, session_id: str = "session-1") -> None:
        await self.proactivity_service.capture_dialogue(
            user_id="user-1",
            session_id=session_id,
            user_text=text,
            reply_text="",
        )

    async def plan_followup(self):
        return await self.proactivity_service.plan_follow_up(user_id="user-1")

    async def mark_followup_sent(self, topic_key: str) -> None:
        await self.proactivity_service.mark_follow_up_sent(user_id="user-1", topic_key=topic_key)

    async def fast_adapt(self, signal_type: str, content: str, session_id: str) -> str | None:
        return await self.personality_evolver.fast_adapt(
            InteractionSignal(
                signal_type=signal_type,
                user_id="user-1",
                session_id=session_id,
                content=content,
                confidence=0.9,
            )
        )

    def prompt_for(self, text: str, session_id: str = "session-1") -> str:
        emotional_context = self.soul_engine._interpret_emotion(text, self.core_memory)
        support_policy = self.soul_engine._build_support_policy(text, self.core_memory, emotional_context)
        return self.soul_engine._build_prompt(
            core_memory=self.core_memory,
            recent_messages=[],
            session_adaptations_live=[],
            mid_term_memories=[],
            retrieved={"matches": []},
            emotional_context=emotional_context,
            support_policy=support_policy,
        )

    def metric(self, name: str, condition: bool, *, score: float | None = None, **details: Any) -> CompanionMetricResult:
        actual_score = score if score is not None else (1.0 if condition else 0.0)
        return CompanionMetricResult(name=name, score=actual_score, passed=condition, details=details)

    def finalize(
        self,
        scenario_id: str,
        metrics: list[CompanionMetricResult],
        *,
        failures: list[str] | None = None,
        journal_events_checked: list[str] | None = None,
    ) -> CompanionEvalResult:
        failures = list(failures or [])
        for metric in metrics:
            if not metric.passed:
                failures.append(metric.name)
        return CompanionEvalResult(
            scenario_id=scenario_id,
            passed=not failures,
            metrics=metrics,
            failures=failures,
            journal_events_checked=list(journal_events_checked or []),
        )


def build_eval_harness() -> EvalHarness:
    core_memory = CoreMemory()
    cache = DummyCoreMemoryCache(core_memory=core_memory)
    session_store = DummySessionContextStore()
    vector_retriever = DummyVectorRetriever(matches=[])
    journal = RecordingJournal()
    scheduler = RecordingScheduler(core_memory)
    graph_store = RecordingGraphStore()
    candidate_manager = EvolutionCandidateManager(journal)
    snapshot_store = PersonalitySnapshotStore()
    governance_mid_term_store = MidTermMemoryStore(dsn="")
    governance_mid_term_store.degraded = True
    governance_mid_term_store.degraded_reason = "test_memory_only"
    governance_mid_term_store.storage_source = "memory_fallback"
    governance_service = MemoryGovernanceService(
        core_memory_cache=cache,
        core_memory_scheduler=scheduler,
        graph_store=graph_store,
        mid_term_memory_store=governance_mid_term_store,
        candidate_manager=candidate_manager,
        evolution_journal=journal,
    )
    proactivity_service = GentleProactivityService(
        core_memory_cache=cache,
        core_memory_scheduler=scheduler,
        evolution_journal=journal,
    )
    personality_evolver = PersonalityEvolver(
        session_context_store=session_store,
        core_memory_cache=cache,
        core_memory_scheduler=scheduler,
        evolution_journal=journal,
        snapshot_store=snapshot_store,
        candidate_manager=candidate_manager,
    )
    relationship_state_machine = RelationshipStateMachine(
        core_memory_cache=cache,
        core_memory_scheduler=scheduler,
        candidate_manager=candidate_manager,
        evolution_journal=journal,
        personality_evolver=personality_evolver,
    )
    cognition_updater = CognitionUpdater(
        core_memory_cache=cache,
        core_memory_scheduler=scheduler,
        graph_store=graph_store,
        candidate_manager=candidate_manager,
        relationship_state_machine=relationship_state_machine,
        memory_governance_service=governance_service,
    )
    soul_mid_term_store = MidTermMemoryStore(dsn="")
    soul_mid_term_store.degraded = True
    soul_mid_term_store.degraded_reason = "test_memory_only"
    soul_mid_term_store.storage_source = "memory_fallback"
    soul_engine = SoulEngine(
        model_registry=DummyModelRegistry(api_key=None),
        core_memory_cache=cache,
        session_context_store=session_store,
        mid_term_memory_store=soul_mid_term_store,
        vector_retriever=vector_retriever,
        tool_registry=DummyToolCatalog(),
        proactivity_service=proactivity_service,
    )
    core_memory.personality.core_personality.behavioral_rules.append(BehavioralRule(rule="Be direct"))
    return EvalHarness(
        core_memory=core_memory,
        cache=cache,
        session_store=session_store,
        vector_retriever=vector_retriever,
        journal=journal,
        scheduler=scheduler,
        graph_store=graph_store,
        candidate_manager=candidate_manager,
        snapshot_store=snapshot_store,
        governance_service=governance_service,
        personality_evolver=personality_evolver,
        relationship_state_machine=relationship_state_machine,
        proactivity_service=proactivity_service,
        cognition_updater=cognition_updater,
        soul_engine=soul_engine,
    )
