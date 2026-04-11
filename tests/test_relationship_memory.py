from __future__ import annotations

from dataclasses import asdict

import pytest

from app.evolution import EvolutionCandidateManager, EvolutionJournal
from app.evolution.cognition_updater import CognitionUpdater
from app.memory.core_memory import CoreMemory, FactualMemory, InferredMemory, RelationshipMemory
from app.memory.core_memory_store import _core_memory_from_dict
from app.tasks.models import Lesson, Task


class DummyCoreMemoryCache:
    def __init__(self, core_memory: CoreMemory | None = None) -> None:
        self.core_memory = core_memory or CoreMemory()

    async def get(self, user_id: str) -> CoreMemory:
        return self.core_memory


class RecordingScheduler:
    def __init__(self, core_memory: CoreMemory) -> None:
        self.core_memory = core_memory
        self.calls: list[tuple[str, str, object, str | None]] = []

    async def write(self, user_id: str, block: str, content: object, event_id: str | None = None) -> CoreMemory:
        self.calls.append((user_id, block, content, event_id))
        if block == "world_model":
            self.core_memory.world_model = content  # type: ignore[assignment]
        elif block == "self_cognition":
            self.core_memory.self_cognition = content  # type: ignore[assignment]
        return self.core_memory


class RecordingGraphStore:
    def __init__(self) -> None:
        self.upserts: list[dict[str, object]] = []

    async def upsert_relation(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)


class RecordingTaskStore:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    async def create(self, task: Task) -> Task:
        self.tasks[task.id] = task
        return task

    async def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    async def update(self, task: Task) -> Task:
        self.tasks[task.id] = task
        return task


class RecordingBlackboard:
    def __init__(self) -> None:
        self.waiting: list[tuple[Task, object]] = []

    async def on_task_waiting_hitl(self, task: Task, request: object) -> None:
        task.status = "waiting_hitl"
        self.waiting.append((task, request))


@pytest.mark.asyncio
async def test_core_memory_store_reads_legacy_world_model_into_structured_facts() -> None:
    snapshot = {
        "world_model": {
            "env_constraints": [{"content": "No direct shell outside workspace", "is_pinned": True}],
            "user_model": {"tone": {"content": "Direct, concise", "is_pinned": False}},
            "agent_profiles": {},
            "social_rules": [{"content": "Do not overpromise"}],
        }
    }

    core_memory = _core_memory_from_dict(snapshot)

    assert len(core_memory.world_model.confirmed_facts) == 3
    assert core_memory.world_model.confirmed_facts[0].source == "legacy_snapshot"
    assert core_memory.world_model.confirmed_facts[0].confirmed_by_user is True


@pytest.mark.asyncio
async def test_cognition_updater_classifies_explicit_user_statement_as_factual_memory() -> None:
    core_memory = CoreMemory()
    scheduler = RecordingScheduler(core_memory)
    candidate_manager = EvolutionCandidateManager(EvolutionJournal())
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        candidate_manager=candidate_manager,
    )
    lesson = Lesson(
        user_id="user-1",
        domain="preferences",
        summary="User prefers concise replies",
        confidence=0.95,
        details={"explicit_user_statement": True, "explicit_user_confirmation": True},
    )

    await updater._update_world_model(lesson)
    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="preferences",
            summary="User prefers concise replies",
            confidence=0.95,
            details={"explicit_user_statement": True, "explicit_user_confirmation": True},
        )
    )

    assert scheduler.calls
    stored = core_memory.world_model.confirmed_facts[0]
    assert isinstance(stored, FactualMemory)
    assert stored.confirmed_by_user is True
    assert stored.truth_type == "fact"


@pytest.mark.asyncio
async def test_cognition_updater_routes_uncertain_inference_to_pending_confirmation() -> None:
    core_memory = CoreMemory()
    scheduler = RecordingScheduler(core_memory)
    task_store = RecordingTaskStore()
    blackboard = RecordingBlackboard()
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        task_store=task_store,
        blackboard=blackboard,
    )
    lesson = Lesson(
        user_id="user-1",
        domain="preferences",
        summary="User may dislike long explanations",
        confidence=0.5,
    )

    await updater._update_world_model(lesson)

    assert core_memory.world_model.pending_confirmations
    pending = core_memory.world_model.pending_confirmations[0]
    assert pending.status == "pending_confirmation"
    assert blackboard.waiting
    task = next(iter(task_store.tasks.values()))
    assert task.metadata["memory_confirmation"]["candidate"]["memory_key"] == pending.memory_key


@pytest.mark.asyncio
async def test_cognition_updater_marks_conflict_instead_of_overwriting_confirmed_fact() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers short answers",
            source="user",
            confidence=1.0,
            confirmed_by_user=True,
            memory_key="fact:preferences:user prefers short answers",
        )
    )
    scheduler = RecordingScheduler(core_memory)
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
    )
    lesson = Lesson(
        user_id="user-1",
        domain="preferences",
        summary="User prefers detailed answers",
        confidence=0.8,
        details={"source": "summary"},
    )

    candidate = InferredMemory(
        content="User prefers detailed answers",
        source="summary",
        confidence=0.8,
        memory_key="fact:preferences:user prefers short answers".replace("fact:", "inference:", 1),
    )
    conflict = updater._detect_conflict(core_memory.world_model.confirmed_facts, candidate)

    assert conflict is not None
    assert conflict.confirmed_by_user is True


@pytest.mark.asyncio
async def test_cognition_updater_preserves_relationship_history_in_graph_store() -> None:
    graph_store = RecordingGraphStore()
    core_memory = CoreMemory()
    scheduler = RecordingScheduler(core_memory)
    candidate_manager = EvolutionCandidateManager(EvolutionJournal())
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=graph_store,
        candidate_manager=candidate_manager,
    )
    lesson = Lesson(
        user_id="user-1",
        summary="User prefers concise replies",
        confidence=0.9,
        subject="user",
        relation="PREFERS",
        object="concise replies",
        details={"explicit_user_statement": True, "explicit_user_confirmation": True},
    )

    await updater._update_world_model(lesson)
    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            summary="User prefers concise replies",
            confidence=0.9,
            subject="user",
            relation="PREFERS",
            object="concise replies",
            details={"explicit_user_statement": True, "explicit_user_confirmation": True},
        )
    )

    assert graph_store.upserts
    assert graph_store.upserts[0]["status"] == "active"
    assert graph_store.upserts[0]["confirmed_by_user"] is True
    assert core_memory.world_model.relationship_history[0].relation == "PREFERS"


@pytest.mark.asyncio
async def test_self_cognition_updates_flow_through_candidate_pipeline_before_apply() -> None:
    core_memory = CoreMemory()
    scheduler = RecordingScheduler(core_memory)
    candidate_manager = EvolutionCandidateManager(EvolutionJournal())
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        candidate_manager=candidate_manager,
    )
    lesson = Lesson(
        user_id="user-1",
        domain="python",
        outcome="done",
        summary="Python task completed successfully",
        is_agent_capability_issue=True,
        details={"session_id": "session-a"},
    )

    await updater._update_self_cognition(lesson)

    assert scheduler.calls == []
    candidate = next(iter(candidate_manager._candidates_by_id.values()))
    assert candidate.affected_area == "self_cognition"
    assert candidate.status == "candidate"

    await updater._update_self_cognition(
        Lesson(
            user_id="user-1",
            domain="python",
            outcome="done",
            summary="Python task completed successfully",
            is_agent_capability_issue=True,
            details={"session_id": "session-b"},
        )
    )

    assert scheduler.calls
    assert core_memory.self_cognition.capability_map["python"].confidence > 0.5


@pytest.mark.asyncio
async def test_hitl_feedback_promotes_pending_memory_after_approval() -> None:
    candidate = InferredMemory(
        content="User may dislike long explanations",
        source="lesson",
        confidence=0.6,
        status="pending_confirmation",
        memory_key="inference:length:long",
    )
    core_memory = CoreMemory()
    core_memory.world_model.pending_confirmations.append(candidate)
    scheduler = RecordingScheduler(core_memory)
    task_store = RecordingTaskStore()
    task = Task(
        metadata={
            "user_id": "user-1",
            "memory_confirmation": {
                "memory_key": candidate.memory_key,
                "candidate": asdict(candidate),
            },
        }
    )
    await task_store.create(task)
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        task_store=task_store,
        blackboard=RecordingBlackboard(),
    )

    await updater.handle_hitl_feedback(
        type("Event", (), {"payload": {"task_id": task.id, "decision": "approve"}})()
    )

    assert not core_memory.world_model.pending_confirmations
    assert core_memory.world_model.inferred_memories[0].confirmed_by_user is True
    assert task_store.tasks[task.id].status == "done"
