from __future__ import annotations

from dataclasses import asdict

import pytest

from app.evolution import EvolutionCandidateManager, EvolutionJournal
from app.evolution.cognition_updater import CognitionUpdater
from app.memory.core_memory import CoreMemory, FactualMemory, InferredMemory, RelationshipMemory
from app.memory.core_memory_store import _core_memory_from_dict
from app.tasks.store import TaskStore
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
    assert core_memory.world_model.relationship_stage.stage == "unfamiliar"
    assert core_memory.world_model.relationship_stage.confidence == 0.0


@pytest.mark.asyncio
async def test_core_memory_store_round_trips_relationship_stage_snapshot() -> None:
    snapshot = {
        "world_model": {
            "relationship_stage": {
                "stage": "stable_companion",
                "confidence": 0.88,
                "updated_at": "2026-04-11T00:00:00+00:00",
                "entered_at": "2026-04-10T00:00:00+00:00",
                "supports_vulnerability": True,
                "repair_needed": False,
                "recent_transition_reason": "Stable relationship evidence accumulated.",
                "recent_shared_events": ["User shared a long-running project update."],
            }
        }
    }

    core_memory = _core_memory_from_dict(snapshot)

    assert core_memory.world_model.relationship_stage.stage == "stable_companion"
    assert core_memory.world_model.relationship_stage.supports_vulnerability is True
    assert core_memory.world_model.relationship_stage.recent_shared_events == [
        "User shared a long-running project update."
    ]


@pytest.mark.asyncio
async def test_core_memory_store_round_trips_proactivity_snapshot_defaults() -> None:
    snapshot = {
        "world_model": {
            "proactivity_policy": {
                "enabled": True,
                "min_interval_hours": 72,
                "same_topic_cooldown_hours": 168,
                "max_followups_per_14_days": 2,
                "updated_at": "2026-04-11T00:00:00+00:00",
            },
            "proactivity_state": {
                "last_user_message_at": "2026-04-11T01:00:00+00:00",
                "latest_preference_override": "allow",
                "pending_opportunities": [
                    {
                        "topic_key": "interview:tomorrow",
                        "summary": "I have a big interview tomorrow.",
                        "importance": "high",
                        "status": "pending",
                    }
                ],
            },
        }
    }

    core_memory = _core_memory_from_dict(snapshot)

    assert core_memory.world_model.proactivity_policy.min_interval_hours == 72
    assert core_memory.world_model.proactivity_state.latest_preference_override == "allow"
    assert core_memory.world_model.proactivity_state.pending_opportunities[0].topic_key == "interview:tomorrow"


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


@pytest.mark.asyncio
async def test_support_preference_lesson_uses_stable_support_memory_key() -> None:
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
        domain="support_preference",
        summary="User prefers listening-first support when emotionally loaded.",
        confidence=0.95,
        details={
            "support_preference": "listening",
            "explicit_user_statement": True,
            "explicit_user_confirmation": True,
            "session_id": "session-a",
        },
    )

    await updater._update_world_model(lesson)
    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="support_preference",
            summary="User prefers listening-first support when emotionally loaded.",
            confidence=0.95,
            details={
                "support_preference": "listening",
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "session_id": "session-b",
            },
        )
    )

    assert scheduler.calls
    assert core_memory.world_model.confirmed_facts[0].memory_key == "support_preference:listening"


@pytest.mark.asyncio
async def test_proactivity_preference_lesson_uses_stable_memory_key() -> None:
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
        domain="proactivity_preference",
        summary="User explicitly does not want proactive follow-up or reminders.",
        confidence=0.95,
        details={
            "proactivity_preference": "suppress",
            "explicit_user_statement": True,
            "explicit_user_confirmation": True,
            "session_id": "session-a",
        },
    )

    await updater._update_world_model(lesson)
    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="proactivity_preference",
            summary="User explicitly does not want proactive follow-up or reminders.",
            confidence=0.95,
            details={
                "proactivity_preference": "suppress",
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "session_id": "session-b",
            },
        )
    )

    assert scheduler.calls
    assert core_memory.world_model.confirmed_facts[0].memory_key == "proactivity_preference:suppress"


@pytest.mark.asyncio
async def test_explicit_preference_lesson_is_promoted_to_factual_memory_with_stable_key() -> None:
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
        domain="explicit_preference",
        summary="User likes Python.",
        confidence=0.96,
        details={
            "preference_relation": "likes",
            "preference_object": "Python",
            "explicit_user_statement": True,
            "explicit_user_confirmation": True,
            "session_id": "session-a",
        },
    )

    await updater._update_world_model(lesson)
    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="explicit_preference",
            summary="User likes Python.",
            confidence=0.96,
            details={
                "preference_relation": "likes",
                "preference_object": "Python",
                "explicit_user_statement": True,
                "explicit_user_confirmation": True,
                "session_id": "session-b",
            },
        )
    )

    assert scheduler.calls
    stored = core_memory.world_model.confirmed_facts[0]
    assert isinstance(stored, FactualMemory)
    assert stored.content == "User likes Python."
    assert stored.memory_key == "fact:explicit_preference:likes:python"


@pytest.mark.asyncio
async def test_reviewed_explicit_preference_requires_confirmation_instead_of_direct_promotion() -> None:
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

    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="explicit_preference",
            summary="User likes Python.",
            confidence=0.58,
            details={
                "preference_relation": "likes",
                "preference_object": "Python",
                "explicit_user_statement": False,
                "explicit_user_confirmation": False,
                "requires_review": True,
            },
        )
    )

    assert core_memory.world_model.pending_confirmations
    pending = core_memory.world_model.pending_confirmations[0]
    assert pending.status == "pending_confirmation"
    assert pending.confirmed_by_user is False
    assert pending.memory_key == "inference:explicit_preference:likes:python"
    assert blackboard.waiting


@pytest.mark.asyncio
async def test_implicit_situational_preference_is_stored_as_short_term_inference_without_confirmation_task() -> None:
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

    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="implicit_preference",
            summary="User may like coffee.",
            confidence=0.63,
            details={
                "preference_relation": "likes",
                "preference_object": "coffee",
                "preference_strength": "implicit",
                "preference_durability": "situational",
                "speaker_attribution": "self_reported",
                "memory_tier": "session_hint",
                "evidence_type": "implicit_expression",
            },
        )
    )

    assert not core_memory.world_model.pending_confirmations
    assert not blackboard.waiting
    stored = core_memory.world_model.inferred_memories[0]
    assert isinstance(stored, InferredMemory)
    assert stored.content == "User may like coffee."
    assert stored.memory_key == "inference:implicit_preference:likes:coffee"
    assert stored.time_horizon == "short_term"
    assert stored.metadata["memory_tier"] == "session_hint"


def test_task_store_serializes_jsonb_fields_for_asyncpg() -> None:
    task = Task(
        id="task-json",
        intent="memory_confirmation",
        result={"ok": True},
        metadata={
            "user_id": "user-1",
            "memory_confirmation": {
                "memory_key": "inference:test",
                "candidate": {"memory_key": "inference:test", "content": "x"},
            },
        },
    )

    payload = TaskStore._serialize_task(task)

    assert isinstance(payload[6], str)
    assert isinstance(payload[14], str)
    assert "\"ok\": true" in payload[6]
    assert "\"memory_confirmation\"" in payload[14]
