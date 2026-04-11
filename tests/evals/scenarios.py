from __future__ import annotations

from app.memory import FactualMemory, InferredMemory, RelationshipMemory
from app.memory.core_memory import BehavioralRule
from app.tasks.models import Lesson

from tests.evals.fixtures import CompanionEvalScenario, CompanionEvalTurn, EvalHarness


async def run_multi_session_memory_accuracy(harness: EvalHarness):
    scenario_id = "multi_session_memory_accuracy"
    failures: list[str] = []

    explicit_lesson = Lesson(
        user_id="user-1",
        domain="preferences",
        summary="User prefers concise replies",
        confidence=0.95,
        details={"explicit_user_statement": True, "explicit_user_confirmation": True, "session_id": "session-a"},
    )
    await harness.cognition_updater._update_world_model(explicit_lesson)
    await harness.cognition_updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="preferences",
            summary="User prefers concise replies",
            confidence=0.95,
            details={"explicit_user_statement": True, "explicit_user_confirmation": True, "session_id": "session-b"},
        )
    )
    listed_before = await harness.governance_service.list_memory(user_id="user-1")
    prompt_before = harness.prompt_for("Can you help again?", session_id="session-b")

    target = next((item for item in harness.core_memory.world_model.confirmed_facts if "concise replies" in item.content), None)
    if target is None:
        failures.append("durable_preference_missing")
    else:
        await harness.governance_service.correct_memory(
            user_id="user-1",
            memory_key=target.memory_key,
            corrected_content="User prefers careful detailed answers",
            truth_type="fact",
        )
    listed_after = await harness.governance_service.list_memory(user_id="user-1")

    metrics = [
        harness.metric(
            "memory_accuracy",
            any(item["content"] == "User prefers careful detailed answers" for item in listed_after),
            expected="corrected durable fact visible",
        ),
        harness.metric(
            "consistency",
            any(item["content"] == "User prefers careful detailed answers" for item in listed_after)
            and not any(item["content"] == "User prefers concise replies" for item in listed_after if item["visibility"] == "durable"),
            before_prompt_contains="User prefers concise replies" in prompt_before,
        ),
        harness.metric(
            "mistaken_learning_rate",
            all(item["content"] != "User prefers concise replies" for item in listed_after if item["visibility"] == "durable"),
            corrected_items=len(listed_after),
            pre_items=len(listed_before),
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        failures=failures,
        journal_events_checked=["memory_governance_corrected"],
    )


async def run_relationship_continuity_progression(harness: EvalHarness):
    scenario_id = "relationship_continuity_progression"
    harness.core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    harness.core_memory.world_model.relationship_history.extend(
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
                content="user KNOWS long-running context",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:KNOWS:long-running context",
                subject="user",
                relation="KNOWS",
                object="long-running context",
            ),
        ]
    )

    await harness.relationship_state_machine.evaluate(user_id="user-1", observation={"summary": "steady positive interaction", "context_id": "s5"})
    await harness.relationship_state_machine.evaluate(user_id="user-1", observation={"summary": "steady positive interaction", "context_id": "s6"})
    prompt = harness.prompt_for("hello again", session_id="s6")

    metrics = [
        harness.metric(
            "relationship_continuity",
            harness.core_memory.world_model.relationship_stage.stage in {"trust_building", "stable_companion"},
            stage=harness.core_memory.world_model.relationship_stage.stage,
        ),
        harness.metric(
            "consistency",
            "Relationship Stage" in prompt and "light familiarity" in prompt,
            prompt_contains_stage="Relationship Stage" in prompt,
        ),
        harness.metric(
            "memory_accuracy",
            len(harness.core_memory.world_model.relationship_history) >= 2 and len(harness.core_memory.world_model.relationship_stage.recent_shared_events) >= 1,
            relationship_history_count=len(harness.core_memory.world_model.relationship_history),
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        journal_events_checked=["evolution_candidate_applied", "relationship_stage_transition_applied"],
    )


async def run_emotional_support_mode_stability(harness: EvalHarness):
    scenario_id = "emotional_support_mode_stability"
    harness.core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    listening_policy = harness.soul_engine._build_support_policy(
        "Please just listen first",
        harness.core_memory,
        harness.soul_engine._interpret_emotion("Please just listen first", harness.core_memory),
    )
    solving_policy = harness.soul_engine._build_support_policy(
        "Tell me what to do right now",
        harness.core_memory,
        harness.soul_engine._interpret_emotion("Tell me what to do right now", harness.core_memory),
    )
    safety_policy = harness.soul_engine._build_support_policy(
        "I can't go on",
        harness.core_memory,
        harness.soul_engine._interpret_emotion("I can't go on", harness.core_memory),
    )

    metrics = [
        harness.metric(
            "consistency",
            listening_policy.support_mode == "listening" and solving_policy.support_mode == "problem_solving",
            listening_mode=listening_policy.support_mode,
            solving_mode=solving_policy.support_mode,
        ),
        harness.metric(
            "felt_understanding_proxy",
            solving_policy.stored_preference == "listening" and solving_policy.support_mode == "problem_solving",
            stored_preference=solving_policy.stored_preference,
        ),
        harness.metric(
            "memory_accuracy",
            safety_policy.support_mode == "safety_constrained",
            safety_mode=safety_policy.support_mode,
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        journal_events_checked=[],
    )


async def run_mistaken_learning_and_governance(harness: EvalHarness):
    scenario_id = "mistaken_learning_and_governance"
    inference = Lesson(
        user_id="user-1",
        domain="preferences",
        summary="User may prefer direct tone",
        confidence=0.8,
        details={"source": "summary", "session_id": "g1"},
    )
    await harness.cognition_updater._update_world_model(inference)
    await harness.cognition_updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="preferences",
            summary="User may prefer direct tone",
            confidence=0.8,
            details={"source": "summary", "session_id": "g2"},
        )
    )
    await harness.governance_service.correct_memory(
        user_id="user-1",
        memory_key="inference:preferences:user may prefer direct tone",
        corrected_content="User prefers careful detailed answers",
        truth_type="fact",
    )
    await harness.governance_service.set_blocked(user_id="user-1", content_class="support_preference", blocked=True)
    await harness.cognition_updater._update_world_model(
        Lesson(
            user_id="user-1",
            domain="support_preference",
            summary="User prefers listening-first support",
            confidence=0.95,
            details={"support_preference": "listening", "explicit_user_statement": True, "explicit_user_confirmation": True, "session_id": "g3"},
        )
    )
    listed = await harness.governance_service.list_memory(user_id="user-1")

    metrics = [
        harness.metric(
            "mistaken_learning_rate",
            not any(item["content"] == "User may prefer direct tone" and item["visibility"] == "durable" for item in listed),
            listed_count=len(listed),
        ),
        harness.metric(
            "memory_accuracy",
            any(item["content"] == "User prefers careful detailed answers" for item in listed),
        ),
        harness.metric(
            "consistency",
            harness.core_memory.world_model.memory_governance.blocked_content_classes == ["support_preference"],
            blocked=harness.core_memory.world_model.memory_governance.blocked_content_classes,
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        journal_events_checked=["memory_governance_corrected", "memory_governance_block_updated"],
    )


async def run_personality_drift_and_rollback(harness: EvalHarness):
    scenario_id = "personality_drift_and_rollback"
    harness.core_memory.personality.core_personality.baseline_description = "Stable baseline"
    harness.core_memory.personality.core_personality.behavioral_rules = [BehavioralRule(rule="Keep a stable tone")]
    harness.personality_evolver.TRAIT_DELTA_THRESHOLD = 0.01
    submission = await harness.candidate_manager.submit(
        user_id="user-1",
        affected_area="personality",
        dedupe_key="trait:directness",
        proposed_change={"kind": "trait_update", "field": "directness", "delta": 0.2},
        evidence_summary="Increase directness substantially",
        rationale="Eval scenario for drift rollback",
        risk_level="low",
        source_event_id="eval-event-1",
        source_context_id="eval-session-1",
    )
    await harness.personality_evolver.apply_candidates("user-1", [submission.candidate], event_id="eval-event-1")
    candidate = harness.candidate_manager.get_candidate(submission.candidate.id)

    metrics = [
        harness.metric(
            "drift_rate",
            candidate is not None and candidate.status == "reverted",
            candidate_status=candidate.status if candidate else "missing",
        ),
        harness.metric(
            "consistency",
            harness.core_memory.personality.core_personality.baseline_description == "Stable baseline",
            baseline=harness.core_memory.personality.core_personality.baseline_description,
        ),
        harness.metric(
            "memory_accuracy",
            harness.core_memory.personality.rollback_count == 1,
            rollback_count=harness.core_memory.personality.rollback_count,
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        journal_events_checked=["personality_rollback", "evolution_candidate_reverted"],
    )


async def run_repair_recovery_continuity(harness: EvalHarness):
    scenario_id = "repair_recovery_continuity"
    harness.core_memory.world_model.relationship_stage.stage = "stable_companion"
    harness.core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User prefers listening-first support",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="support_preference:listening",
        )
    )
    for context_id in ("r1", "r2", "r3"):
        await harness.relationship_state_machine.evaluate(
            user_id="user-1",
            observation={"summary": "The user said the assistant misunderstood an important boundary.", "context_id": context_id},
        )
    repair_prompt = harness.prompt_for("Can we keep talking?", session_id="r3")
    harness.core_memory.world_model.memory_conflicts = []
    harness.core_memory.world_model.relationship_history.extend(
        [
            RelationshipMemory(
                content="user TRUSTS stable support",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:TRUSTS:stable support",
                subject="user",
                relation="KNOWS",
                object="stable support",
            ),
            RelationshipMemory(
                content="user RETURNS after repair",
                source="lesson",
                confidence=0.9,
                confirmed_by_user=True,
                memory_key="relationship:user:KNOWS:returns after repair",
                subject="user",
                relation="KNOWS",
                object="returns after repair",
            ),
        ]
    )
    await harness.relationship_state_machine.evaluate(user_id="user-1", observation={"summary": "steady positive interaction", "context_id": "r4"})
    await harness.relationship_state_machine.evaluate(user_id="user-1", observation={"summary": "steady positive interaction", "context_id": "r5"})
    recovered_stage = harness.core_memory.world_model.relationship_stage.stage

    metrics = [
        harness.metric(
            "relationship_continuity",
            recovered_stage in {"trust_building", "stable_companion"},
            recovered_stage=recovered_stage,
        ),
        harness.metric(
            "felt_understanding_proxy",
            "reduce assertive memory claims" in repair_prompt.lower() or "avoid overfamiliar phrasing" in repair_prompt.lower(),
            repair_prompt=repair_prompt,
        ),
        harness.metric(
            "consistency",
            any(entry.event_type == "relationship_stage_transition_applied" for entry in harness.journal.entries),
            journal_count=len(harness.journal.entries),
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        journal_events_checked=["relationship_stage_transition_applied", "evolution_candidate_applied"],
    )


async def run_gentle_proactivity_bounds(harness: EvalHarness):
    scenario_id = "gentle_proactivity_bounds"
    harness.core_memory.world_model.relationship_stage.stage = "stable_companion"
    harness.core_memory.world_model.confirmed_facts.append(
        FactualMemory(
            content="User explicitly allows gentle follow-up on important topics.",
            source="dialogue_signal",
            confidence=0.95,
            confirmed_by_user=True,
            memory_key="proactivity_preference:allow",
        )
    )
    await harness.capture_dialogue(
        "I have a big interview tomorrow and I'm anxious about it.",
        session_id="p1",
    )
    first = await harness.plan_followup()
    if first.eligible:
        await harness.mark_followup_sent(first.topic_key)
    second = await harness.plan_followup()
    prompt = harness.prompt_for("Can we talk?", session_id="p2")

    metrics = [
        harness.metric(
            "consistency",
            first.eligible and not second.eligible,
            first_reason=first.reason,
            second_reason=second.reason,
        ),
        harness.metric(
            "relationship_continuity",
            first.relationship_stage == "stable_companion",
            stage=first.relationship_stage,
        ),
        harness.metric(
            "felt_understanding_proxy",
            "Earlier you mentioned" in first.draft_message and "No pressure to reply" in first.draft_message,
            draft=first.draft_message,
        ),
        harness.metric(
            "memory_accuracy",
            "Proactivity Policy" in prompt and "- stored_preference=allow" in prompt,
        ),
    ]
    return harness.finalize(
        scenario_id,
        metrics,
        journal_events_checked=["proactivity_opportunity_captured", "proactivity_followup_sent"],
    )


COMPANION_EVAL_SCENARIOS = [
    CompanionEvalScenario(
        scenario_id="multi_session_memory_accuracy",
        description="Durable memory survives across sessions and governance correction removes old truth.",
        turns=[
            CompanionEvalTurn(name="explicit_preference_a", session_id="session-a", user_text="I prefer concise replies."),
            CompanionEvalTurn(name="explicit_preference_b", session_id="session-b", user_text="Still keep replies concise."),
            CompanionEvalTurn(name="governance_correction", session_id="session-c", user_text="Actually I want careful detailed answers."),
        ],
        runner=run_multi_session_memory_accuracy,
    ),
    CompanionEvalScenario(
        scenario_id="relationship_continuity_progression",
        description="Relationship evidence pushes stage progression and prompt constraints together.",
        turns=[
            CompanionEvalTurn(name="support_preference_1", session_id="s1", user_text="Please listen first."),
            CompanionEvalTurn(name="support_preference_2", session_id="s2", user_text="Please listen first again."),
            CompanionEvalTurn(name="positive_continuity", session_id="s6", user_text="Let's continue where we left off."),
        ],
        runner=run_relationship_continuity_progression,
    ),
    CompanionEvalScenario(
        scenario_id="emotional_support_mode_stability",
        description="Stored support preference does not override explicit current-turn intent or safety constraints.",
        turns=[
            CompanionEvalTurn(name="listening_turn", session_id="e1", user_text="Please just listen first."),
            CompanionEvalTurn(name="solving_turn", session_id="e2", user_text="Tell me what to do right now."),
            CompanionEvalTurn(name="safety_turn", session_id="e3", user_text="I can't go on."),
        ],
        runner=run_emotional_support_mode_stability,
    ),
    CompanionEvalScenario(
        scenario_id="mistaken_learning_and_governance",
        description="Wrong inference can be corrected and future learning can be blocked deterministically.",
        turns=[
            CompanionEvalTurn(name="wrong_inference_1", session_id="g1", user_text="Maybe the system inferred the wrong tone."),
            CompanionEvalTurn(name="wrong_inference_2", session_id="g2", user_text="That wrong tone inference repeated."),
            CompanionEvalTurn(name="block_support_learning", session_id="g3", user_text="Do not learn support style from this."),
        ],
        runner=run_mistaken_learning_and_governance,
    ),
    CompanionEvalScenario(
        scenario_id="personality_drift_and_rollback",
        description="High drift on personality change reverts candidate and preserves stable baseline.",
        turns=[
            CompanionEvalTurn(name="drift_candidate", session_id="eval-session-1", user_text="Large trait delta candidate."),
        ],
        runner=run_personality_drift_and_rollback,
    ),
    CompanionEvalScenario(
        scenario_id="repair_recovery_continuity",
        description="Repair stage is entered after rupture and can recover through bounded positive evidence.",
        turns=[
            CompanionEvalTurn(name="repair_signal_1", session_id="r1", user_text="You misunderstood an important boundary."),
            CompanionEvalTurn(name="repair_signal_2", session_id="r2", user_text="That still felt off."),
            CompanionEvalTurn(name="recovery", session_id="r5", user_text="Let's keep going carefully."),
        ],
        runner=run_repair_recovery_continuity,
    ),
    CompanionEvalScenario(
        scenario_id="gentle_proactivity_bounds",
        description="Proactive follow-up stays stage-gated, low-frequency, and conservatively worded.",
        turns=[
            CompanionEvalTurn(name="important_topic", session_id="p1", user_text="I have a big interview tomorrow and I'm anxious about it."),
            CompanionEvalTurn(name="followup_window", session_id="p2", user_text="No new user turn required; planner should throttle."),
        ],
        runner=run_gentle_proactivity_bounds,
    ),
]
