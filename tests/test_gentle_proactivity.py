from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.evolution.proactivity import GentleProactivityService
from app.memory import AgentContinuityState, CoreMemory, FactualMemory, UserEmotionalState

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


class RecordingPlatformAdapter:
    def __init__(self) -> None:
        self.outbound: list[tuple[object, object]] = []

    async def send_outbound(self, ctx: object, message: object) -> None:
        self.outbound.append((ctx, message))


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


@pytest.mark.asyncio
async def test_gentle_proactivity_suppresses_followup_when_emotional_risk_is_active() -> None:
    core_memory, service = build_service()
    core_memory.world_model.relationship_stage.stage = "stable_companion"
    core_memory.user_emotional_state = UserEmotionalState(
        emotion_class="anxiety",
        intensity="high",
        emotional_risk="medium",
        support_mode="listening",
        support_preference="listening",
        stability="fragile",
        unresolved_topics=["work"],
        carryover_summary="User remains highly stressed about work.",
        last_observed_at=datetime.now(timezone.utc).isoformat(),
        carryover_until=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-1",
        user_text="I have a deadline tomorrow and I'm worried about it.",
    )
    decision = await service.plan_follow_up(user_id="user-1")

    assert decision.eligible is False
    assert decision.reason == "emotional_risk_active"


@pytest.mark.asyncio
async def test_gentle_proactivity_suppresses_followup_when_agent_repair_mode_is_active() -> None:
    core_memory, service = build_service()
    core_memory.world_model.relationship_stage.stage = "stable_companion"
    core_memory.agent_continuity_state = AgentContinuityState(
        caution_level="high",
        warmth_level="medium",
        repair_mode=True,
        recovery_mode=False,
        relational_confidence=0.35,
        continuity_summary="The agent is in a repair posture after a recent miss.",
        active_signals=["task_failure"],
        last_event_at=datetime.now(timezone.utc).isoformat(),
        last_shift_reason="Recent failure increased caution.",
    )

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-1",
        user_text="I have a big interview tomorrow and I'm anxious about it.",
    )
    decision = await service.plan_follow_up(user_id="user-1")

    assert decision.eligible is False
    assert decision.reason == "agent_repair_mode_active"


def test_gentle_proactivity_prompt_snapshot_surfaces_continuity_context() -> None:
    core_memory, service = build_service()
    core_memory.user_emotional_state = UserEmotionalState(
        emotion_class="sadness",
        intensity="medium",
        emotional_risk="low",
        support_mode="listening",
        support_preference="listening",
        stability="fragile",
        unresolved_topics=["relationship"],
        carryover_summary="User has unresolved relationship sadness.",
        last_observed_at=datetime.now(timezone.utc).isoformat(),
        carryover_until=(datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
    )
    core_memory.agent_continuity_state = AgentContinuityState(
        caution_level="high",
        warmth_level="medium",
        repair_mode=False,
        recovery_mode=True,
        relational_confidence=0.55,
        continuity_summary="Agent is being more conservative after recent repair work.",
        active_signals=["task_success"],
        last_event_at=datetime.now(timezone.utc).isoformat(),
        last_shift_reason="Recent repair phase ended.",
    )

    snapshot = service.prompt_policy_snapshot(core_memory)

    assert snapshot["emotional_carryover"] == "sadness"
    assert snapshot["agent_caution_level"] == "high"
    assert "Agent caution is elevated" in snapshot["policy_hint"]


@pytest.mark.asyncio
async def test_gentle_proactivity_deliver_follow_up_sends_message_and_marks_sent() -> None:
    core_memory, service = build_service()
    core_memory.world_model.relationship_stage.stage = "stable_companion"
    platform = RecordingPlatformAdapter()

    await service.capture_dialogue(
        user_id="user-1",
        session_id="session-1",
        user_text="I have a big interview tomorrow and I'm anxious about it.",
    )
    decision = await service.deliver_follow_up(
        user_id="user-1",
        ctx=type("Ctx", (), {"session_id": "session-1", "user_id": "user-1"})(),
        platform_adapter=platform,
    )

    assert decision.eligible is True
    assert platform.outbound
    _, outbound = platform.outbound[0]
    assert outbound.metadata["proactive"] is True
    assert core_memory.world_model.proactivity_state.last_topic_key == decision.topic_key
