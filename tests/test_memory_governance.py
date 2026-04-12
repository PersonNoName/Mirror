from __future__ import annotations

from dataclasses import asdict

import pytest

from app.evolution import CognitionUpdater, EvolutionCandidateManager, EvolutionJournal
from app.memory import CoreMemory, FactualMemory, InferredMemory, MemoryGovernanceService, RelationshipMemory
from app.memory.core_memory_store import _core_memory_from_dict
from app.tasks.models import Lesson
from tests.conftest import DummyMidTermMemoryStore


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
        return self.core_memory


class RecordingGraphStore:
    def __init__(self) -> None:
        self.superseded: list[dict[str, object]] = []
        self.upserts: list[dict[str, object]] = []

    async def supersede_relation(self, **kwargs: object) -> None:
        self.superseded.append(kwargs)

    async def upsert_relation(self, **kwargs: object) -> None:
        self.upserts.append(kwargs)


@pytest.mark.asyncio
async def test_core_memory_store_reads_default_memory_governance_policy() -> None:
    core_memory = _core_memory_from_dict({"world_model": {}})

    assert core_memory.world_model.memory_governance.blocked_content_classes == []
    assert core_memory.world_model.memory_governance.retention_days["candidate"] == 7


@pytest.mark.asyncio
async def test_memory_governance_lists_durable_and_candidate_memory() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers short answers",
            source="user",
            confidence=1.0,
            confirmed_by_user=True,
            memory_key="fact:preferences:short",
        )
    )
    manager = EvolutionCandidateManager(EvolutionJournal())
    await manager.submit(
        user_id="user-1",
        affected_area="world_model",
        dedupe_key="inference:tone:direct",
        proposed_change={"memory": asdict(InferredMemory(content="User may prefer direct tone", source="lesson", memory_key="inference:tone:direct"))},
        evidence_summary="User may prefer direct tone",
        rationale="test",
        risk_level="low",
    )
    service = MemoryGovernanceService(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=RecordingScheduler(core_memory),
        graph_store=RecordingGraphStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        candidate_manager=manager,
        evolution_journal=EvolutionJournal(),
    )

    items = await service.list_memory(user_id="user-1")

    assert any(item["visibility"] == "durable" for item in items)
    assert any(item["visibility"] == "candidate" for item in items)


@pytest.mark.asyncio
async def test_memory_governance_corrects_inference_into_user_confirmed_fact() -> None:
    core_memory = CoreMemory()
    original = InferredMemory(
        content="User may prefer direct tone",
        source="lesson",
        confidence=0.7,
        memory_key="inference:tone:direct",
    )
    core_memory.world_model.inferred_memories.append(original)
    scheduler = RecordingScheduler(core_memory)
    service = MemoryGovernanceService(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        candidate_manager=EvolutionCandidateManager(EvolutionJournal()),
        evolution_journal=EvolutionJournal(),
    )

    item = await service.correct_memory(
        user_id="user-1",
        memory_key="inference:tone:direct",
        corrected_content="User prefers careful detailed answers",
        truth_type="fact",
    )

    assert item["source"] == "user_correction"
    assert core_memory.world_model.inferred_memories[0].status == "superseded"
    assert core_memory.world_model.confirmed_facts[-1].confirmed_by_user is True


@pytest.mark.asyncio
async def test_memory_governance_correction_supersedes_all_active_duplicates_for_same_key() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.confirmed_facts.extend(
        [
            FactualMemory(
                content="User prefers concise replies",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="fact:preferences:concise",
            ),
            FactualMemory(
                content="User prefers concise replies",
                source="lesson",
                confidence=0.95,
                confirmed_by_user=True,
                memory_key="fact:preferences:concise",
            ),
        ]
    )
    service = MemoryGovernanceService(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=RecordingScheduler(core_memory),
        graph_store=RecordingGraphStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        candidate_manager=EvolutionCandidateManager(EvolutionJournal()),
        evolution_journal=EvolutionJournal(),
    )

    await service.correct_memory(
        user_id="user-1",
        memory_key="fact:preferences:concise",
        corrected_content="User prefers careful detailed answers",
        truth_type="fact",
    )
    listed = await service.list_memory(user_id="user-1")

    assert sum(1 for item in listed if item["memory_key"] == "fact:preferences:concise") == 1
    assert listed[0]["content"] == "User prefers careful detailed answers"


@pytest.mark.asyncio
async def test_memory_governance_delete_marks_relationship_deleted_and_reverts_candidate() -> None:
    core_memory = CoreMemory()
    relationship = RelationshipMemory(
        content="user PREFERS concise replies",
        source="lesson",
        confidence=0.9,
        confirmed_by_user=True,
        memory_key="relationship:user:PREFERS:concise replies",
        subject="user",
        relation="PREFERS",
        object="concise replies",
    )
    core_memory.world_model.relationship_history.append(relationship)
    manager = EvolutionCandidateManager(EvolutionJournal())
    submission = await manager.submit(
        user_id="user-1",
        affected_area="world_model",
        dedupe_key="relationship:user:PREFERS:concise replies",
        proposed_change={"memory": asdict(relationship)},
        evidence_summary=relationship.content,
        rationale="test",
        risk_level="low",
    )
    graph_store = RecordingGraphStore()
    service = MemoryGovernanceService(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=RecordingScheduler(core_memory),
        graph_store=graph_store,
        mid_term_memory_store=DummyMidTermMemoryStore(),
        candidate_manager=manager,
        evolution_journal=EvolutionJournal(),
    )

    await service.delete_memory(user_id="user-1", memory_key=relationship.memory_key, reason="wrong")

    assert core_memory.world_model.relationship_history[0].metadata["deleted_by_user"] is True
    assert graph_store.superseded
    assert manager.get_candidate(submission.candidate.id).status == "reverted"


@pytest.mark.asyncio
async def test_cognition_updater_respects_blocked_support_preference_learning() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.memory_governance.blocked_content_classes = ["support_preference"]
    scheduler = RecordingScheduler(core_memory)
    manager = EvolutionCandidateManager(EvolutionJournal())
    service = MemoryGovernanceService(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        candidate_manager=manager,
        evolution_journal=EvolutionJournal(),
    )
    updater = CognitionUpdater(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        graph_store=RecordingGraphStore(),
        candidate_manager=manager,
        memory_governance_service=service,
    )

    await updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="support_preference",
            summary="User prefers listening-first support",
            confidence=0.95,
            details={"support_preference": "listening", "explicit_user_statement": True, "explicit_user_confirmation": True},
        )
    )

    assert manager.list_candidates(user_id="user-1", affected_area="world_model") == []
    assert scheduler.calls == []


@pytest.mark.asyncio
async def test_memory_governance_prunes_expired_inference_and_pending_memory() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.inferred_memories.append(
        InferredMemory(
            content="Old inference",
            source="lesson",
            confidence=0.6,
            updated_at="2025-01-01T00:00:00+00:00",
            memory_key="inference:old",
        )
    )
    core_memory.world_model.pending_confirmations.append(
        InferredMemory(
            content="Old pending",
            source="lesson",
            confidence=0.6,
            updated_at="2025-01-01T00:00:00+00:00",
            status="pending_confirmation",
            memory_key="pending:old",
        )
    )
    service = MemoryGovernanceService(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=RecordingScheduler(core_memory),
        graph_store=RecordingGraphStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        candidate_manager=EvolutionCandidateManager(EvolutionJournal()),
        evolution_journal=EvolutionJournal(),
    )

    pruned = service.prune_world_model(core_memory.world_model)

    assert pruned.inferred_memories == []
    assert pruned.pending_confirmations == []
