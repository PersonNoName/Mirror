from __future__ import annotations

import pytest

from app.evolution import EvolutionCandidateManager, EvolutionJournal, PersonalityEvolver, RelationshipStateMachine
from app.memory import CoreMemory, FactualMemory, RelationshipMemory


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
        elif block == "personality":
            self.core_memory.personality = content  # type: ignore[assignment]
        return self.core_memory


class DummySessionContextStore:
    async def get_adaptations(self, user_id: str, session_id: str) -> list[str]:
        return []

    async def set_adaptations(self, user_id: str, session_id: str, adaptations: list[str]) -> None:
        return None


class RecordingJournal(EvolutionJournal):
    def __init__(self) -> None:
        super().__init__(dsn="")
        self.degraded = True


class DummySnapshotStore:
    async def save(self, user_id: str, personality_state: object, reason: str = "") -> object:
        return type("Snapshot", (), {"version": getattr(personality_state, "version", 1), "created_at": "now"})()

    async def rollback(self, user_id: str) -> object | None:
        return None


@pytest.mark.asyncio
async def test_relationship_state_machine_defaults_to_unfamiliar() -> None:
    core_memory = CoreMemory()
    scheduler = RecordingScheduler(core_memory)
    machine = RelationshipStateMachine(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        candidate_manager=EvolutionCandidateManager(RecordingJournal()),
    )

    stage = await machine.evaluate(user_id="user-1", observation={"summary": "hello", "context_id": "s1"})

    assert stage.stage == "unfamiliar"


@pytest.mark.asyncio
async def test_relationship_state_machine_moves_to_trust_building_after_repeated_stable_signals() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    core_memory.world_model.relationship_history.extend(
        [
            RelationshipMemory(
                content="user PREFERS concise replies",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:PREFERS:concise replies",
                subject="user",
                relation="PREFERS",
                object="concise replies",
            ),
            RelationshipMemory(
                content="user VALUES continuity",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:VALUES:continuity",
                subject="user",
                relation="VALUES",
                object="continuity",
            ),
        ]
    )
    scheduler = RecordingScheduler(core_memory)
    manager = EvolutionCandidateManager(RecordingJournal())
    machine = RelationshipStateMachine(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        candidate_manager=manager,
    )

    await machine.evaluate(user_id="user-1", observation={"summary": "steady positive interaction", "context_id": "s1"})
    await machine.evaluate(user_id="user-1", observation={"summary": "steady positive interaction", "context_id": "s2"})

    assert scheduler.calls
    assert core_memory.world_model.relationship_stage.stage == "trust_building"
    candidate = next(iter(manager._candidates_by_id.values()))
    assert candidate.metadata["relationship_stage_to"] == "trust_building"


@pytest.mark.asyncio
async def test_relationship_state_machine_enters_vulnerable_support_on_trust_base() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.relationship_stage.stage = "trust_building"
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    core_memory.world_model.relationship_history.extend(
        [
            RelationshipMemory(
                content="user TRUSTS stable support",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:TRUSTS:stable support",
                subject="user",
                relation="TRUSTS",
                object="stable support",
            ),
            RelationshipMemory(
                content="user RETURNS to ongoing conversations",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:RETURNS:ongoing conversations",
                subject="user",
                relation="RETURNS",
                object="ongoing conversations",
            ),
        ]
    )
    scheduler = RecordingScheduler(core_memory)
    manager = EvolutionCandidateManager(RecordingJournal())
    machine = RelationshipStateMachine(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        candidate_manager=manager,
    )

    await machine.evaluate(
        user_id="user-1",
        observation={"summary": "User feels overwhelmed and needs support", "emotional_risk": "medium", "context_id": "s1"},
    )
    await machine.evaluate(
        user_id="user-1",
        observation={"summary": "User feels overwhelmed and needs support", "emotional_risk": "medium", "context_id": "s2"},
    )

    assert core_memory.world_model.relationship_stage.stage == "vulnerable_support"
    assert core_memory.world_model.relationship_stage.supports_vulnerability is True


@pytest.mark.asyncio
async def test_relationship_state_machine_enters_repair_and_recovery_from_repair_signal() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.relationship_stage.stage = "stable_companion"
    scheduler = RecordingScheduler(core_memory)
    manager = EvolutionCandidateManager(RecordingJournal())
    machine = RelationshipStateMachine(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        candidate_manager=manager,
    )

    await machine.evaluate(
        user_id="user-1",
        observation={"summary": "The user said the assistant misunderstood an important boundary.", "context_id": "s1"},
    )
    await machine.evaluate(
        user_id="user-1",
        observation={"summary": "The user said the assistant misunderstood an important boundary.", "context_id": "s2"},
    )
    await machine.evaluate(
        user_id="user-1",
        observation={"summary": "The user said the assistant misunderstood an important boundary.", "context_id": "s3"},
    )

    assert core_memory.world_model.relationship_stage.stage == "repair_and_recovery"
    journal_entry = manager.evolution_journal._memory[-1]
    assert journal_entry.details["relationship_stage_to"] == "repair_and_recovery"
    assert "transition_reason" in journal_entry.details


@pytest.mark.asyncio
async def test_relationship_state_machine_applies_bounded_style_adjustment() -> None:
    core_memory = CoreMemory()
    core_memory.world_model.relationship_stage.stage = "trust_building"
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    core_memory.world_model.relationship_history.extend(
        [
            RelationshipMemory(
                content="user TRUSTS stable support",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:TRUSTS:stable support",
                subject="user",
                relation="TRUSTS",
                object="stable support",
            ),
            RelationshipMemory(
                content="user RETURNS to ongoing conversations",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:RETURNS:ongoing conversations",
                subject="user",
                relation="RETURNS",
                object="ongoing conversations",
            ),
            RelationshipMemory(
                content="user SHARES long-running projects",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:SHARES:long-running projects",
                subject="user",
                relation="SHARES",
                object="long-running projects",
            ),
        ]
    )
    scheduler = RecordingScheduler(core_memory)
    manager = EvolutionCandidateManager(RecordingJournal())
    evolver = PersonalityEvolver(
        session_context_store=DummySessionContextStore(),
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        evolution_journal=RecordingJournal(),
        snapshot_store=DummySnapshotStore(),
        candidate_manager=manager,
    )
    machine = RelationshipStateMachine(
        core_memory_cache=DummyCoreMemoryCache(core_memory),
        core_memory_scheduler=scheduler,
        candidate_manager=manager,
        personality_evolver=evolver,
    )

    original_warmth = core_memory.personality.relationship_style.warmth
    await machine.evaluate(user_id="user-1", observation={"summary": "positive continuity", "context_id": "s1"})
    await machine.evaluate(user_id="user-1", observation={"summary": "positive continuity", "context_id": "s2"})
    await machine.evaluate(user_id="user-1", observation={"summary": "positive continuity", "context_id": "s3"})
    await machine.evaluate(user_id="user-1", observation={"summary": "positive continuity", "context_id": "s4"})

    assert core_memory.world_model.relationship_stage.stage == "stable_companion"
    assert core_memory.personality.relationship_style.warmth >= original_warmth
