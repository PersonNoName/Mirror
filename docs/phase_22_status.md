# Phase 22 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 22

## Phase
- name: `Phase 22 - Companion Evaluation Suite`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_21_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added a dedicated companion evaluation slice under:
  - `tests/evals/`
- introduced structured evaluation data contracts in:
  - `tests/evals/fixtures.py`
- added deterministic eval-layer types:
  - `CompanionEvalScenario`
  - `CompanionEvalTurn`
  - `CompanionEvalResult`
  - `CompanionMetricResult`
- added a reusable in-process `EvalHarness` that wires:
  - `SoulEngine`
  - `CognitionUpdater`
  - `PersonalityEvolver`
  - `RelationshipStateMachine`
  - `MemoryGovernanceService`
  - journal / candidate / snapshot / world-model state
- kept the harness local and deterministic:
  - no real Redis
  - no real Postgres
  - no real Neo4j
  - no real Qdrant
  - no external judge model
- added scenario pack definitions in:
  - `tests/evals/scenarios.py`
- implemented six long-horizon companion scenarios:
  - `multi_session_memory_accuracy`
  - `relationship_continuity_progression`
  - `emotional_support_mode_stability`
  - `mistaken_learning_and_governance`
  - `personality_drift_and_rollback`
  - `repair_recovery_continuity`
- fixed the companion metric set and made it explicit:
  - `memory_accuracy`
  - `consistency`
  - `felt_understanding_proxy`
  - `relationship_continuity`
  - `mistaken_learning_rate`
  - `drift_rate`
- added top-level evaluation tests in:
  - `tests/test_companion_evals.py`
- `test_companion_evals.py` now verifies:
  - each named scenario passes
  - each scenario emits structured metric results
  - the suite aggregates all required metric names
  - aggregate metric scores meet the deterministic pass threshold
- updated `pytest.ini` with an explicit:
  - `eval` marker
- kept the evaluation suite low-intrusion:
  - no production endpoint changes
  - no runtime contract changes
  - no new storage backend or telemetry dependency

## Important Implementation Notes
- Phase 22 evaluation is rule-based and local:
  - it does not attempt to judge open-ended model quality
  - it measures companion-system behavior that is already under deterministic control
- “felt understanding” is implemented as a proxy metric, not a human-like subjective grader:
  - correct memory use
  - correct support-mode routing
  - correct repair-stage prompt constraint
- the new eval harness is intentionally separate from the existing unit tests:
  - existing tests remain focused on individual modules and APIs
  - Phase 22 adds cross-cutting multi-turn and multi-session regression coverage
- scenario runners intentionally reuse already-implemented Phase16-21 capabilities rather than adding mock-only product behavior
- the suite is designed so later phases can add scenarios without changing production code

## Verification Completed
- targeted evaluation suite:
  - `python -m pytest tests/test_companion_evals.py`
  - result: `7 passed`
- full test suite:
  - `python -m pytest`
  - result: `112 passed`
- bytecode compile:
  - `python -m compileall app tests`

## Explicitly Not Done Yet
- no external benchmark runner or offline scoring CLI beyond `pytest`
- no persisted historical eval result store
- no human annotation pipeline
- no model-vs-model comparative harness
- no Phase23 proactivity scenarios yet
- no Phase24 dependency-risk or manipulative-language scenario pack yet

## Handoff Rule For Future Codex
- keep companion evals deterministic and repo-local unless a later phase explicitly introduces a heavier evaluation system
- add new long-horizon companion regressions by extending:
  - `tests/evals/fixtures.py`
  - `tests/evals/scenarios.py`
  - `tests/test_companion_evals.py`
  rather than scattering cross-session assertions into unrelated unit tests
- preserve the fixed companion metric vocabulary unless a later phase intentionally revises it:
  - `memory_accuracy`
  - `consistency`
  - `felt_understanding_proxy`
  - `relationship_continuity`
  - `mistaken_learning_rate`
  - `drift_rate`
- if future phases introduce new companion behaviors such as proactivity or dependency-boundary enforcement, add scenario-level regression coverage here before expanding product logic further
