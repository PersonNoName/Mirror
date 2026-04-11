from __future__ import annotations

import pytest

from app.evolution import EvolutionCandidateManager, EvolutionJournal


@pytest.mark.asyncio
async def test_low_risk_candidate_applies_after_two_evidence_points() -> None:
    manager = EvolutionCandidateManager(EvolutionJournal())

    first = await manager.submit(
        user_id="user-1",
        affected_area="world_model",
        dedupe_key="fact:preferences:concise",
        proposed_change={"memory_key": "fact:preferences:concise"},
        evidence_summary="User prefers concise replies",
        rationale="Repeated explicit statements",
        risk_level="low",
        source_event_id="event-1",
        source_context_id="session-a",
    )
    second = await manager.submit(
        user_id="user-1",
        affected_area="world_model",
        dedupe_key="fact:preferences:concise",
        proposed_change={"memory_key": "fact:preferences:concise"},
        evidence_summary="User prefers concise replies",
        rationale="Repeated explicit statements",
        risk_level="low",
        source_event_id="event-2",
        source_context_id="session-b",
    )

    assert first.action == "hold"
    assert second.action == "apply"
    assert second.candidate.evidence_count == 2


@pytest.mark.asyncio
async def test_medium_risk_candidate_requires_extra_evidence_across_contexts() -> None:
    manager = EvolutionCandidateManager(EvolutionJournal())

    for index in range(2):
        result = await manager.submit(
            user_id="user-1",
            affected_area="self_cognition",
            dedupe_key="self_cognition:python",
            proposed_change={"domain": "python"},
            evidence_summary="Python limitation observed",
            rationale="Repeated failures should change self-cognition slowly",
            risk_level="medium",
            source_event_id=f"event-{index}",
            source_context_id="session-a" if index == 0 else "session-b",
        )
        assert result.action == "hold"
        assert result.candidate.status == "pending"

    final = await manager.submit(
        user_id="user-1",
        affected_area="self_cognition",
        dedupe_key="self_cognition:python",
        proposed_change={"domain": "python"},
        evidence_summary="Python limitation observed",
        rationale="Repeated failures should change self-cognition slowly",
        risk_level="medium",
        source_event_id="event-3",
        source_context_id="session-c",
    )

    assert final.action == "apply"
    assert final.candidate.evidence_count == 3


@pytest.mark.asyncio
async def test_high_risk_candidate_stays_pending_and_affects_summary() -> None:
    manager = EvolutionCandidateManager(EvolutionJournal())

    result = await manager.submit(
        user_id="user-1",
        affected_area="personality",
        dedupe_key="trait:boundary_strength",
        proposed_change={"kind": "trait_update", "field": "boundary_strength", "delta": 0.25},
        evidence_summary="Boundary strength changing sharply",
        rationale="Large personality movement should require explicit approval",
        risk_level="high",
        source_event_id="event-1",
        source_context_id="session-a",
    )

    assert result.action == "hitl"
    assert result.candidate.status == "pending"
    assert manager.summary()["high_risk_pending_count"] == 1
