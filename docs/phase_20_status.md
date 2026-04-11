# Phase 20 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 20

## Phase
- name: `Phase 20 - Relationship State Machine`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_19_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added explicit relationship-stage state to `WorldModel` in:
  - `app/memory/core_memory.py`
- introduced `RelationshipStageState` with:
  - `stage`
  - `confidence`
  - `updated_at`
  - `entered_at`
  - `supports_vulnerability`
  - `repair_needed`
  - `recent_transition_reason`
  - `recent_shared_events`
- fixed the relationship-stage enum to:
  - `unfamiliar`
  - `trust_building`
  - `stable_companion`
  - `vulnerable_support`
  - `repair_and_recovery`
- updated `app/memory/core_memory_store.py` so:
  - new `relationship_stage` snapshots round-trip correctly
  - legacy world-model snapshots without the field load as:
    - `stage=unfamiliar`
    - `confidence=0.0`
    - empty transition/event fields
- updated `app/evolution/core_memory_scheduler.py` so world-model compression/truncation preserves:
  - `relationship_stage`
  - bounded `recent_shared_events`
- added `app/evolution/relationship_state_machine.py`
- implemented a bounded `RelationshipStateMachine` that:
  - reads durable relationship evidence from `WorldModel`
  - accepts current observation hints from the lesson/update path
  - derives a recommended stage using explicit heuristics instead of turn-count rules
  - submits stage changes through the Phase 18 candidate pipeline
  - emits bounded relationship-style nudges through the same candidate pipeline
  - exposes a prompt-facing policy snapshot
- stage derivation now covers:
  - `unfamiliar -> trust_building`
  - `trust_building -> stable_companion`
  - trust-based escalation into `vulnerable_support`
  - rupture/repair detection into `repair_and_recovery`
  - bounded recovery from `repair_and_recovery` back into lower-risk trust stages
- preserved key policy constraints:
  - no single positive interaction jumps directly to `stable_companion`
  - `vulnerable_support` only appears on top of an existing trust base
  - `repair_and_recovery` has higher priority than ordinary positive progression
- updated `app/evolution/cognition_updater.py` so:
  - world-model lesson application can trigger relationship-stage evaluation
  - HITL memory confirmation writes also trigger stage reevaluation
  - `world_model` candidate application now supports explicit `relationship_stage` payloads
- extended `app/evolution/candidate_pipeline.py` journal details with:
  - `relationship_stage_from`
  - `relationship_stage_to`
  - `transition_reason`
- exposed a public `apply_candidates()` helper in:
  - `app/evolution/personality_evolver.py`
  - this is used for approved stage-driven `relationship_style` nudges
- updated `app/runtime/bootstrap.py` so runtime now wires:
  - `RelationshipStateMachine`
  - `CognitionUpdater -> relationship_state_machine`
  - runtime health snapshot fields:
    - `relationship_stage_enabled`
    - `relationship_stage_degraded`
- updated `app/soul/engine.py` so prompt assembly now includes:
  - `Relationship Stage`
  - current stage
  - confidence
  - recent transition reason
  - bounded behavior hint
  - recent shared events summary
- kept relationship-stage effects bounded to:
  - tone/boundary hints
  - memory-reference confidence hints
  - support-continuity framing
- did not expand relationship stage into:
  - core identity mutation
  - therapy claims
  - new external API surface

## Important Implementation Notes
- relationship stage is now the prompt-facing truth source for current relational posture:
  - `WorldModel.relationship_history` remains historical evidence
  - `WorldModel.relationship_stage` is the current snapshot
- the state machine is heuristic and deterministic:
  - no new pre-LLM classifier was introduced
  - stage transitions are unit-testable without model calls
- relationship-stage candidates use the existing Phase 18 pipeline:
  - `affected_area="world_model"` for stage transitions
  - `affected_area="relationship_style"` for bounded style nudges
- stage-driven style changes remain intentionally small:
  - `unfamiliar` slightly strengthens boundaries
  - `stable_companion` slightly increases warmth/supportiveness
  - `repair_and_recovery` temporarily strengthens boundaries and reduces overfamiliarity
- transition journal visibility is preserved via candidate details plus an explicit:
  - `relationship_stage_transition_applied` event
- `recent_shared_events` is intentionally tiny and prompt-facing:
  - it is derived from existing durable memory
  - it is not backed by a new persistence subsystem

## Verification Completed
- targeted Phase 20 regression suite:
  - `python -m pytest tests/test_relationship_state_machine.py tests/test_relationship_memory.py tests/test_soul_engine.py tests/test_runtime_bootstrap.py`
  - result: `24 passed`
- full test suite:
  - `python -m pytest`
  - result: `96 passed`
- bytecode compile:
  - `python -m compileall app tests`

## Explicitly Not Done Yet
- no user-visible relationship-stage UI or manual override surface
- no dedicated `/relationship` endpoint or stage inspection endpoint
- no richer rupture taxonomy beyond bounded repair/misunderstanding heuristics
- no proactive behavior engine that uses relationship stage to autonomously initiate outreach
- no long-horizon event summarizer beyond the small `recent_shared_events` prompt summary

## Handoff Rule For Future Codex
- keep `relationship_stage` and `relationship_style` separate:
  - stage is the bounded policy state
  - style is the foreground expression tendency
- do not reintroduce silent relationship-stage mutation outside the candidate pipeline
- preserve journal visibility for every stage transition; future changes must keep:
  - `relationship_stage_from`
  - `relationship_stage_to`
  - `transition_reason`
- if future phases add richer relationship recovery modeling, extend the current deterministic rules before considering opaque model-based transition logic
- if future work increases proactive behavior, route it through stage-aware policy constraints instead of letting `stable_companion` or `vulnerable_support` imply open-ended intimacy
