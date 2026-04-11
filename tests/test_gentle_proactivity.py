from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.evolution.proactivity import GentleProactivityService
from app.memory import CoreMemory, FactualMemory

from tests.conftest import DummyCoreMemoryCache


class RecordingScheduler:
    def __init__(self, core_memory: CoreMemory) -> None:
        self.core_memory = core_memory
        self.calls: list[tuple[str, str]] = []

    async def write(self, user_id: str, block: str, content: object, event_id: str | None = None) -> CoreMemory:
        self.calls.append((user_id, block))
        if block == "world_model":
            self.core_memory.world_model = content  # type: ignore[assignment]
        return self.core_memory


def build_service(core_memory: CoreMemory | None = None) -> tuple[CoreMemory, GentleProactivityService]:
    memory = core_memory or CoreMemory()
    scheduler = RecordingScheduler(memory)
    service = GentleProactivityService(
        core_memory_cache=DummyCoreMemoryCache(core_memory=memory),
        core_memory_scheduler=scheduler,
        evolution_journal=None,
    )
    return memory, service


@pytest.mark.asyncio
async def test_gentle_proactivity_requires_relationship_stage_before_followup() -> None:
    core_memory, service = build_service()

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-1",
        user_text="I have a big interview tomorrow and I'm anxious about it.",
    )
    decision = await service.plan_follow_up(user_id="user-1")

    assert decision.eligible is False
    assert decision.reason == "relationship_stage_unfamiliar"

    core_memory.world_model.relationship_stage.stage = "stable_companion"
    decision = await service.plan_follow_up(user_id="user-1")

    assert decision.eligible is True
    assert "Earlier you mentioned" in decision.draft_message
    assert "No pressure to reply" in decision.draft_message


@pytest.mark.asyncio
async def test_gentle_proactivity_respects_explicit_suppress_preference() -> None:
    core_memory, service = build_service()
    core_memory.world_model.relationship_stage.stage = "stable_companion"
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User explicitly does not want proactive follow-up or reminders.",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="proactivity_preference:suppress",
        )
    )

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-1",
        user_text="I have a deadline next week and it's stressful.",
    )
    decision = await service.plan_follow_up(user_id="user-1")

    assert decision.eligible is False
    assert decision.reason == "user_preference_suppressed"
    assert decision.stored_preference == "suppress"


@pytest.mark.asyncio
async def test_gentle_proactivity_throttles_recent_followups_and_same_topic_repetition() -> None:
    core_memory, service = build_service()
    core_memory.world_model.relationship_stage.stage = "stable_companion"

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-1",
        user_text="I have a deadline tomorrow and I'm worried about it.",
    )
    first = await service.plan_follow_up(user_id="user-1")
    assert first.eligible is True

    sent_at = datetime.now(timezone.utc)
    await service.mark_follow_up_sent(user_id="user-1", topic_key=first.topic_key, now=sent_at)

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-2",
        user_text="I have a deadline tomorrow and I'm worried about it.",
    )
    second = await service.plan_follow_up(user_id="user-1", now=sent_at + timedelta(hours=1))
    assert second.eligible is False
    assert second.reason == "followup_interval_throttled"

    core_memory.world_model.proactivity_state.last_proactive_at = (sent_at - timedelta(days=4)).isoformat()
    third = await service.plan_follow_up(user_id="user-1", now=sent_at + timedelta(days=4))
    assert third.eligible is False
    assert third.reason == "same_topic_cooldown"
