from __future__ import annotations

from copy import deepcopy

import pytest

from app.evolution import EvolutionCandidate, EvolutionEntry, InteractionSignal, PersonalityEvolver
from app.memory import BehavioralRule, CoreMemory
from app.memory.core_memory_store import _core_memory_from_dict
from app.stability.snapshot import PersonalitySnapshotStore


class RecordingSessionContextStore:
    def __init__(self) -> None:
        self._adaptations: dict[tuple[str, str], list[str]] = {}

    async def get_adaptations(self, user_id: str, session_id: str) -> list[str]:
        return list(self._adaptations.get((user_id, session_id), []))

    async def set_adaptations(self, user_id: str, session_id: str, adaptations: list[str]) -> None:
        self._adaptations[(user_id, session_id)] = list(adaptations)


class RecordingCoreMemoryCache:
    def __init__(self, core_memory: CoreMemory | None = None) -> None:
        self.core_memory = core_memory or CoreMemory()

    async def get(self, user_id: str) -> CoreMemory:
        return self.core_memory


class RecordingScheduler:
    def __init__(self, core_memory: CoreMemory) -> None:
        self.core_memory = core_memory
        self.calls: list[tuple[str, str, object, str | None]] = []

    async def write(
        self,
        user_id: str,
        block: str,
        content: object,
        event_id: str | None = None,
    ) -> CoreMemory:
        self.calls.append((user_id, block, deepcopy(content), event_id))
        if block == "personality":
            self.core_memory.personality = deepcopy(content)  # type: ignore[assignment]
        return self.core_memory


class RecordingJournal:
    def __init__(self) -> None:
        self.entries: list[EvolutionEntry] = []

    async def record(self, entry: EvolutionEntry) -> None:
        self.entries.append(entry)


def build_signal(signal_type: str, content: str, session_id: str) -> InteractionSignal:
    return InteractionSignal(
        signal_type=signal_type,
        user_id="user-1",
        session_id=session_id,
        content=content,
        confidence=0.9,
    )


def build_evolver(core_memory: CoreMemory | None = None) -> tuple[PersonalityEvolver, RecordingSessionContextStore, RecordingScheduler, RecordingJournal, PersonalitySnapshotStore, RecordingCoreMemoryCache]:
    memory = core_memory or CoreMemory()
    session_store = RecordingSessionContextStore()
    cache = RecordingCoreMemoryCache(memory)
    scheduler = RecordingScheduler(memory)
    journal = RecordingJournal()
    snapshot_store = PersonalitySnapshotStore()
    evolver = PersonalityEvolver(
        session_context_store=session_store,
        core_memory_cache=cache,
        core_memory_scheduler=scheduler,
        evolution_journal=journal,
        snapshot_store=snapshot_store,
    )
    return evolver, session_store, scheduler, journal, snapshot_store, cache


@pytest.mark.asyncio
async def test_core_memory_store_reads_legacy_personality_into_three_layer_state() -> None:
    payload = {
        "personality": {
            "baseline_description": "Direct, technical, collaborative.",
            "behavioral_rules": [{"rule": "Be direct", "source": "legacy", "confidence": 0.8}],
            "traits_internal": {"directness": 0.7},
            "session_adaptations": ["Keep answers short"],
            "version": 3,
        }
    }

    core_memory = _core_memory_from_dict(payload)

    assert core_memory.personality.core_personality.baseline_description == "Direct, technical, collaborative."
    assert core_memory.personality.core_personality.behavioral_rules[0].rule == "Be direct"
    assert core_memory.personality.session_adaptation.current_items == ["Keep answers short"]
    assert core_memory.personality.version == 3


@pytest.mark.asyncio
async def test_fast_adapt_updates_only_session_layer() -> None:
    core_memory = CoreMemory()
    core_memory.personality.core_personality.behavioral_rules.append(BehavioralRule(rule="Stay stable"))
    evolver, session_store, scheduler, journal, _snapshot_store, cache = build_evolver(core_memory)

    result = await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-a"))

    assert result == "Use shorter replies"
    assert await session_store.get_adaptations("user-1", "session-a") == ["Use shorter replies"]
    assert await session_store.get_adaptations("user-1", "session-b") == []
    assert scheduler.calls == []
    assert cache.core_memory.personality.core_personality.behavioral_rules[0].rule == "Stay stable"
    assert journal.entries[-1].event_type == "session_adaptation_applied"


@pytest.mark.asyncio
async def test_slow_evolve_creates_snapshot_and_promotes_long_term_rule() -> None:
    core_memory = CoreMemory()
    evolver, _session_store, scheduler, journal, snapshot_store, cache = build_evolver(core_memory)

    await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-a"))
    await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-c"))
    await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-b"))

    await evolver.slow_evolve("user-1")
    await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-d"))
    await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-e"))
    await evolver.fast_adapt(build_signal("prefer_concise", "Use shorter replies", "session-f"))
    await evolver.slow_evolve("user-1")

    assert scheduler.calls
    updated = cache.core_memory.personality
    assert updated.version == 2
    assert updated.core_personality.version == 2
    assert updated.core_personality.behavioral_rules[0].rule == "Use shorter replies"
    assert updated.snapshot_version == 1
    assert updated.last_snapshot_at
    assert updated.session_adaptation.current_items == []
    records = await snapshot_store.list_records("user-1")
    assert len(records) == 1
    assert any(entry.event_type == "evolution_candidate_applied" for entry in journal.entries)
    assert journal.entries[-1].event_type == "personality_evolved"


@pytest.mark.asyncio
async def test_slow_evolve_rolls_back_when_drift_detected() -> None:
    core_memory = CoreMemory()
    core_memory.personality.core_personality.baseline_description = "Stable baseline"
    core_memory.personality.core_personality.behavioral_rules.append(BehavioralRule(rule="Keep a stable tone"))
    evolver, _session_store, scheduler, journal, _snapshot_store, cache = build_evolver(core_memory)
    evolver.TRAIT_DELTA_THRESHOLD = 0.01

    submission = await evolver.candidate_manager.submit(
        user_id="user-1",
        affected_area="personality",
        dedupe_key="trait:directness",
        proposed_change={"kind": "trait_update", "field": "directness", "delta": 0.2},
        evidence_summary="Increase directness substantially",
        rationale="Regression test for drift rollback",
        risk_level="low",
        source_event_id="event-1",
        source_context_id="session-a",
    )

    await evolver._apply_personality_candidates("user-1", [submission.candidate])

    assert scheduler.calls
    rolled_back = cache.core_memory.personality
    assert rolled_back.rollback_count == 1
    assert rolled_back.core_personality.baseline_description == "Stable baseline"
    assert [rule.rule for rule in rolled_back.core_personality.behavioral_rules] == ["Keep a stable tone"]
    assert evolver.candidate_manager.get_candidate(submission.candidate.id).status == "reverted"
    assert journal.entries[-1].event_type == "personality_rollback"


@pytest.mark.asyncio
async def test_high_risk_personality_candidate_goes_to_hitl_instead_of_auto_apply() -> None:
    core_memory = CoreMemory()
    evolver, _session_store, scheduler, journal, _snapshot_store, _cache = build_evolver(core_memory)
    evolver.TRAIT_DELTA_THRESHOLD = 0.05

    await evolver.fast_adapt(build_signal("support_more", "Offer more support", "session-a"))
    await evolver.fast_adapt(build_signal("support_more", "Offer more support", "session-b"))
    await evolver.fast_adapt(build_signal("support_more", "Offer more support", "session-c"))

    await evolver.slow_evolve("user-1")

    assert scheduler.calls == []
    assert any(entry.event_type == "evolution_candidate_pending" for entry in journal.entries)


@pytest.mark.asyncio
async def test_snapshot_store_supports_latest_version_and_rollback() -> None:
    snapshot_store = PersonalitySnapshotStore()
    state = CoreMemory().personality
    state.version = 2
    await snapshot_store.save("user-1", state, reason="v2")
    state2 = deepcopy(state)
    state2.version = 3
    await snapshot_store.save("user-1", state2, reason="v3")

    latest = await snapshot_store.latest("user-1")
    version2 = await snapshot_store.get_version("user-1", 2)
    rolled_back = await snapshot_store.rollback("user-1")

    assert latest.version == 3
    assert version2.version == 2
    assert rolled_back.version == 3
