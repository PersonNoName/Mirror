from __future__ import annotations

import pytest

from app.memory import (
    AgentContinuityState,
    BehavioralRule,
    CapabilityEntry,
    CoreMemory,
    FactualMemory,
    InferredMemory,
    MemoryEntry,
    RelationshipStageState,
    RelationshipMemory,
    UserEmotionalState,
)
from app.platform.base import InboundMessage, PlatformContext
from app.providers.openai_compat import ProviderRequestError
from app.soul import SoulEngine

from tests.conftest import (
    DummyChatModel,
    DummyCoreMemoryCache,
    DummyMidTermMemoryStore,
    DummyModelRegistry,
    DummySessionContextStore,
    DummyToolCatalog,
    DummyVectorRetriever,
)


def build_message(text: str = "hello") -> InboundMessage:
    ctx = PlatformContext(platform="web", user_id="user-1", session_id="session-1", capabilities={"streaming"})
    return InboundMessage(text=text, user_id="user-1", session_id="session-1", platform_ctx=ctx)


@pytest.mark.asyncio
async def test_soul_engine_run_parses_valid_action() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "<inner_thoughts>think</inner_thoughts>"
                        "<action>direct_reply</action>"
                        "<content>hello back</content>"
                    )
                }
            }
        ]
    }
    engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=DummyChatModel(response=response)),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )

    action = await engine.run(build_message())

    assert action.type == "direct_reply"
    assert action.content == "hello back"
    assert action.inner_thoughts == "think"
    assert action.metadata["brain"]["self_cognition"]
    assert action.metadata["brain"]["user_emotional_state"]
    assert action.metadata["brain"]["agent_continuity_state"]
    assert action.metadata["brain"]["tool_list"]


@pytest.mark.asyncio
async def test_soul_engine_streams_direct_reply_content_incrementally() -> None:
    stream_chunks = [
        {"choices": [{"delta": {"content": "<inner_thoughts>think</inner_thoughts><action>direct_reply</action><content>Hello"}}]},
        {"choices": [{"delta": {"content": " streamed"}}]},
        {"choices": [{"delta": {"content": " world</content>"}}]},
    ]
    chat_model = DummyChatModel(
        response=None,
        stream_chunks=stream_chunks,
    )
    engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=chat_model),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )
    deltas: list[str] = []

    async def collect(delta: str) -> None:
        deltas.append(delta)

    action = await engine.run(build_message(), on_direct_reply_delta=collect)

    assert action.type == "direct_reply"
    assert action.content == "Hello streamed world"
    assert action.streamed is True
    assert "".join(deltas) == "Hello streamed world"
    assert chat_model.stream_calls


@pytest.mark.asyncio
async def test_soul_engine_high_risk_emotional_message_short_circuits_to_safe_reply() -> None:
    chat_model = DummyChatModel(
        response={
            "choices": [
                {
                    "message": {
                        "content": (
                            "<inner_thoughts>delegate</inner_thoughts>"
                            "<action>publish_task</action>"
                            "<content>dangerous</content>"
                        )
                    }
                }
            ]
        }
    )
    engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=chat_model),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )

    action = await engine.run(build_message("I want to kill myself and I can't go on"))

    assert action.type == "direct_reply"
    assert "immediate risk" in action.content
    assert action.metadata["emotional_risk"] == "high"
    assert action.metadata["brain"]["emotional_context"]
    assert chat_model.calls == []


def test_parse_action_rejects_invalid_action_type() -> None:
    parsed = SoulEngine._parse_action(
        "<inner_thoughts>x</inner_thoughts><action>bad_action</action><content>y</content>"
    )

    assert parsed is None


@pytest.mark.asyncio
async def test_soul_engine_falls_back_when_api_key_missing() -> None:
    engine = SoulEngine(
        model_registry=DummyModelRegistry(api_key=None),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )

    action = await engine.run(build_message("need help"))

    assert action.type == "direct_reply"
    assert "fallback mode" in action.content
    assert "need help" in action.content


@pytest.mark.asyncio
async def test_soul_engine_falls_back_when_provider_raises() -> None:
    engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=DummyChatModel(error=ProviderRequestError("boom"))),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )

    action = await engine.run(build_message("provider error"))

    assert action.type == "direct_reply"
    assert "fallback mode" in action.content


@pytest.mark.asyncio
async def test_soul_engine_falls_back_to_generate_when_stream_not_supported() -> None:
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        "<inner_thoughts>think</inner_thoughts>"
                        "<action>direct_reply</action>"
                        "<content>hello from generate</content>"
                    )
                }
            }
        ]
    }
    chat_model = DummyChatModel(response=response, stream_chunks=None)
    engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=chat_model),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )

    action = await engine.run(build_message(), on_direct_reply_delta=lambda _delta: _noop())

    assert action.content == "hello from generate"
    assert chat_model.calls
    assert chat_model.stream_calls


async def _noop() -> None:
    return None


@pytest.mark.asyncio
async def test_soul_engine_falls_back_when_response_is_unparsable() -> None:
    response = {"choices": [{"message": {"content": "plain text with no action tags"}}]}
    engine = SoulEngine(
        model_registry=DummyModelRegistry(chat_model=DummyChatModel(response=response)),
        core_memory_cache=DummyCoreMemoryCache(),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(),
        tool_registry=DummyToolCatalog(),
    )

    action = await engine.run(build_message("unparsable"))

    assert action.type == "direct_reply"
    assert action.raw_response == "plain text with no action tags"


def test_soul_engine_build_prompt_formats_memory_blocks_for_model_usefulness() -> None:
    core_memory = CoreMemory()
    core_memory.self_cognition.capability_map["retrieval"] = CapabilityEntry(
        description="Can retrieve prior context",
        confidence=0.8,
        limitations=["Needs indexed memory"],
    )
    core_memory.self_cognition.known_limits.append(MemoryEntry(content="Cannot browse private sites"))
    core_memory.self_cognition.mission_clarity.append(MemoryEntry(content="Optimize for truthful responses"))
    core_memory.self_cognition.blindspots.append(MemoryEntry(content="May miss missing external context"))
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="No direct shell outside workspace",
            source="system",
            confidence=1.0,
            confirmed_by_user=True,
            memory_key="fact:env:shell",
        )
    )
    core_memory.world_model.inferred_memories.append(
        InferredMemory(
            content="User prefers direct, concise answers",
            source="dialogue_summary",
            confidence=0.7,
            memory_key="inference:tone:direct",
        )
    )
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User explicitly allows gentle follow-up on important topics.",
            source="dialogue_signal",
            confidence=0.92,
            confirmed_by_user=True,
            memory_key="proactivity_preference:allow",
        )
    )
    core_memory.world_model.relationship_history.append(
        RelationshipMemory(
            content="user PREFERS concise responses",
            source="lesson",
            confidence=0.9,
            confirmed_by_user=True,
            memory_key="relationship:user:PREFERS:concise",
            subject="user",
            relation="PREFERS",
            object="concise responses",
        )
    )
    core_memory.world_model.pending_confirmations.append(
        InferredMemory(
            content="User may dislike long explanations",
            source="lesson",
            confidence=0.6,
            status="pending_confirmation",
            memory_key="inference:length:long",
        )
    )
    core_memory.world_model.memory_conflicts.append(
        InferredMemory(
            content="User wants detailed responses",
            source="lesson",
            confidence=0.6,
            status="conflicted",
            memory_key="inference:length:detailed",
        )
    )
    core_memory.personality.core_personality.baseline_description = "Direct, technical, collaborative."
    core_memory.personality.core_personality.behavioral_rules.append(BehavioralRule(rule="Be direct"))
    core_memory.personality.relationship_style.warmth = 0.45
    core_memory.personality.relationship_style.boundary_strength = 0.88
    core_memory.personality.relationship_style.supportiveness = 0.61
    core_memory.personality.relationship_style.preferred_closeness = "steady"
    core_memory.world_model.relationship_stage = RelationshipStageState(
        stage="repair_and_recovery",
        confidence=0.82,
        recent_transition_reason="Recent repair signal detected.",
        repair_needed=True,
        recent_shared_events=["User said the assistant misunderstood an important boundary."],
    )
    core_memory.personality.session_adaptation.current_items = ["Keep answers short"]
    core_memory.task_experience.lesson_digest.append(MemoryEntry(content="Prefer bounded retries"))
    core_memory.task_experience.domain_tips["python"] = [MemoryEntry(content="Prefer pytest for test coverage")]
    core_memory.task_experience.agent_habits["web_agent"] = [MemoryEntry(content="Summarize sources truthfully")]
    core_memory.user_emotional_state = UserEmotionalState(
        emotion_class="anxiety",
        intensity="medium",
        emotional_risk="low",
        support_mode="listening",
        support_preference="listening",
        stability="fragile",
        unresolved_topics=["work"],
        carryover_summary="User has been stressed about work recently.",
        last_observed_at="2026-04-12T00:00:00+00:00",
        carryover_until="2026-04-18T00:00:00+00:00",
    )
    core_memory.agent_continuity_state = AgentContinuityState(
        caution_level="medium",
        warmth_level="medium",
        repair_mode=False,
        recovery_mode=True,
        relational_confidence=0.62,
        continuity_summary="Recent successful turns allow slightly more continuity.",
        active_signals=["task_success"],
        last_event_at="2026-04-12T00:00:00+00:00",
        last_shift_reason="Recovered after a successful task.",
    )

    engine = SoulEngine(
        model_registry=DummyModelRegistry(),
        core_memory_cache=DummyCoreMemoryCache(core_memory=core_memory),
        session_context_store=DummySessionContextStore(
            recent_messages=[{"role": "user", "content": "hello before"}],
            adaptations=["Keep answers short"],
        ),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(
            matches=[
                {
                    "namespace": "experience",
                    "content": "Previous lesson",
                    "truth_type": "inference",
                    "status": "pending_confirmation",
                }
            ]
        ),
        tool_registry=DummyToolCatalog(tools=[{"name": "search", "description": "Search docs", "schema": {}}]),
    )

    prompt = engine._build_prompt(
        core_memory=core_memory,
        recent_messages=[{"role": "user", "content": "hello before"}],
        session_adaptations_live=["Keep answers short"],
        mid_term_memories=[],
        retrieved={
            "matches": [
                {
                    "namespace": "experience",
                    "content": "Previous lesson",
                    "truth_type": "inference",
                    "status": "pending_confirmation",
                }
            ]
        },
        emotional_context=engine._interpret_emotion("I feel overwhelmed today", core_memory),
        support_policy=engine._build_support_policy(
            "I feel overwhelmed today",
            core_memory,
            engine._interpret_emotion("I feel overwhelmed today", core_memory),
        ),
    )

    assert "SelfCognition(" not in prompt
    assert "WorldModel(" not in prompt
    assert "TaskExperience(" not in prompt
    assert "Capabilities:" in prompt
    assert "retrieval: Can retrieve prior context | confidence=0.80 | limitations=Needs indexed memory" in prompt
    assert "Known Limits:" in prompt
    assert "Cannot browse private sites" in prompt
    assert "Stable Identity" in prompt
    assert "Baseline: Direct, technical, collaborative." in prompt
    assert "Behavioral Rules:" in prompt
    assert "- Be direct" in prompt
    assert "Relationship Style" in prompt
    assert "- warmth=0.45" in prompt
    assert "- boundary_strength=0.88" in prompt
    assert "Relationship Stage" in prompt
    assert "- stage=repair_and_recovery" in prompt
    assert "- repair_needed=true" in prompt
    assert "Reduce assertive memory claims and avoid overfamiliar phrasing." in prompt
    assert "Proactivity Policy" in prompt
    assert "- stored_preference=allow" in prompt
    assert "Emotional Context" in prompt
    assert "- emotion_class=overwhelm" in prompt
    assert "User Emotional State" in prompt
    assert "- active=true" in prompt
    assert "User has been stressed about work recently." in prompt
    assert "Agent Continuity State" in prompt
    assert "- recovery_mode=true" in prompt
    assert "Support Policy" in prompt
    assert "- support_mode=listening" in prompt
    assert "Session Adaptation" in prompt
    assert "These adaptations are temporary and only apply to the current session." in prompt
    assert "Keep answers short" in prompt
    assert "Confirmed Facts:" in prompt
    assert "[fact|confirmed|confidence=1.00|source=system] No direct shell outside workspace" in prompt
    assert "[support_preference|fact|confirmed|confidence=0.95|source=dialogue_signal] User prefers listening-first support" in prompt
    assert "[proactivity_preference|fact|confirmed|confidence=0.92|source=dialogue_signal] User explicitly allows gentle follow-up on important topics." in prompt
    assert "Inferred Memory:" in prompt
    assert "User prefers direct, concise answers" in prompt
    assert "Relationship History:" in prompt
    assert "user PREFERS concise responses" in prompt
    assert "Pending Confirmation:" in prompt
    assert "User may dislike long explanations" in prompt
    assert "Memory Conflicts:" in prompt
    assert "User wants detailed responses" in prompt
    assert "Domain Tips:" in prompt
    assert "python: Prefer pytest for test coverage" in prompt
    assert "Agent Habits:" in prompt
    assert "web_agent: Summarize sources truthfully" in prompt
    assert "## Retrieved Context" in prompt
    assert "- [experience|inference|pending_confirmation] Previous lesson" in prompt


def test_soul_engine_build_prompt_uses_stable_empty_memory_fallbacks() -> None:
    core_memory = CoreMemory()
    engine = SoulEngine(
        model_registry=DummyModelRegistry(),
        core_memory_cache=DummyCoreMemoryCache(core_memory=core_memory),
        session_context_store=DummySessionContextStore(),
        mid_term_memory_store=DummyMidTermMemoryStore(),
        vector_retriever=DummyVectorRetriever(matches=[]),
        tool_registry=DummyToolCatalog(),
    )

    prompt = engine._build_prompt(
        core_memory=core_memory,
        recent_messages=[],
        session_adaptations_live=[],
        mid_term_memories=[],
        retrieved={"matches": []},
        emotional_context=engine._interpret_emotion("hello", core_memory),
        support_policy=engine._build_support_policy(
            "hello",
            core_memory,
            engine._interpret_emotion("hello", core_memory),
        ),
    )

    assert "SelfCognition(" not in prompt
    assert "WorldModel(" not in prompt
    assert "TaskExperience(" not in prompt
    assert "- No explicit capabilities recorded." in prompt
    assert "- No confirmed facts recorded." in prompt
    assert "No active cross-session emotional carryover." in prompt
    assert "No active cross-session agent continuity shift." in prompt
    assert "No active session adaptations for this session." in prompt
    assert "- No lesson digests recorded." in prompt
    assert "- No retrieved context." in prompt


def test_support_policy_prefers_current_explicit_request_over_stored_preference() -> None:
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

    emotional_context = SoulEngine._interpret_emotion("Tell me what to do right now", core_memory)
    policy = SoulEngine._build_support_policy("Tell me what to do right now", core_memory, emotional_context)

    assert policy.stored_preference == "listening"
    assert policy.inferred_preference == "problem_solving"
    assert policy.support_mode == "problem_solving"


def test_emotional_carryover_survives_new_session_until_it_expires() -> None:
    core_memory = CoreMemory()
    core_memory.user_emotional_state = UserEmotionalState(
        emotion_class="sadness",
        intensity="medium",
        emotional_risk="low",
        support_mode="listening",
        support_preference="listening",
        stability="fragile",
        unresolved_topics=["relationship"],
        carryover_summary="User was working through a difficult relationship issue.",
        last_observed_at="2026-04-12T00:00:00+00:00",
        carryover_until="2026-04-18T00:00:00+00:00",
    )

    emotional_context = SoulEngine._interpret_emotion("how is your family doing", core_memory)
    policy = SoulEngine._build_support_policy("how is your family doing", core_memory, emotional_context)

    assert emotional_context.emotion_class == "sadness"
    assert emotional_context.duration_hint == "carryover"
    assert policy.support_mode == "listening"


def test_emotional_carryover_expires_after_decay_window() -> None:
    core_memory = CoreMemory()
    core_memory.user_emotional_state = UserEmotionalState(
        emotion_class="sadness",
        intensity="medium",
        emotional_risk="low",
        support_mode="listening",
        support_preference="listening",
        stability="fragile",
        unresolved_topics=["relationship"],
        carryover_summary="Old emotional carryover.",
        last_observed_at="2026-03-20T00:00:00+00:00",
        carryover_until="2026-03-27T00:00:00+00:00",
    )

    emotional_context = SoulEngine._interpret_emotion("hello again", core_memory)

    assert emotional_context.emotion_class == "neutral"
    assert emotional_context.duration_hint == "unknown"
