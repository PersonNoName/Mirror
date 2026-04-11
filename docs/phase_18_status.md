# Phase 18 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 18

## Phase
- name: `Phase 18 - Controlled Evolution Pipeline`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_17_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added controlled evolution candidate models and in-memory manager in:
  - `app/evolution/candidate_pipeline.py`
- introduced explicit candidate lifecycle types:
  - `EvolutionCandidate`
  - `EvolutionCandidateStatus`
  - `EvolutionRiskLevel`
  - `EvolutionAffectedArea`
  - `EvolutionSubmissionResult`
- implemented candidate aggregation keyed by:
  - `user_id`
  - `affected_area`
  - `dedupe_key`
- implemented default risk policy in `EvolutionCandidateManager`:
  - low risk auto-apply threshold: `evidence_count >= 2`
  - medium risk auto-apply threshold: `evidence_count >= 3`
  - medium risk requires at least `2` unique context ids
  - high risk never auto-applies and returns `hitl`
- standardized candidate lifecycle journal events:
  - `evolution_candidate_created`
  - `evolution_candidate_updated`
  - `evolution_candidate_pending`
  - `evolution_candidate_applied`
  - `evolution_candidate_reverted`
- normalized journal `details` fields for candidate lifecycle:
  - `candidate_id`
  - `candidate_status`
  - `risk_level`
  - `affected_area`
  - `evidence_count`
  - `dedupe_key`
  - `proposed_change`
  - `rollback_reason`
- rewired `app/evolution/cognition_updater.py` so:
  - self-cognition updates submit `self_cognition` candidates first
  - world-model updates submit `world_model` candidates first
  - direct long-term world-model writes now happen only after candidate apply
  - Phase 16 `memory_confirmation` flow remains separate for sensitive or low-confidence memory
  - high-risk evolution candidates can create HITL tasks with `evolution_candidate` metadata
- rewired `app/evolution/personality_evolver.py` so:
  - `slow_evolve()` no longer mutates long-term personality immediately
  - long-term rule promotion, trait changes, and relationship-style changes become candidates first
  - apply-ready candidates are applied in a controlled batch
  - snapshot creation still happens before long-term personality apply
  - drift rollback now marks related candidates as `reverted`
  - high-risk personality candidates use HITL instead of auto-apply
- extended HITL payload contracts in:
  - `app/tasks/models.py`
  - added `EvolutionCandidateRequest`
- updated runtime wiring in:
  - `app/runtime/bootstrap.py`
- runtime now injects one shared `EvolutionCandidateManager` into:
  - `CognitionUpdater`
  - `PersonalityEvolver`
- runtime `/health` snapshot now exposes:
  - `pending_candidate_count`
  - `high_risk_pending_count`
  - `recent_reverted_count`
  - `degraded`
- exported new evolution pipeline types from:
  - `app/evolution/__init__.py`
- exported new HITL request type from:
  - `app/tasks/__init__.py`
- added Phase 18 coverage in:
  - `tests/test_evolution_pipeline.py`
  - updated `tests/test_personality_evolver.py`
  - updated `tests/test_relationship_memory.py`
  - updated `tests/test_runtime_bootstrap.py`
  - updated `tests/test_failure_semantics.py`
  - updated `tests/test_observability.py`

## Important Implementation Notes
- the candidate manager is intentionally in-memory only for Phase 18:
  - no new database tables were introduced
  - lifecycle durability remains aligned with the existing lightweight snapshot/journal level
- `memory_confirmation` and `evolution_candidate` are now two distinct HITL paths:
  - `memory_confirmation` is still for truth confirmation of sensitive or uncertain memory
  - `evolution_candidate` is for high-risk application approval
- world-model writes are now split into two phases:
  - lesson classification and candidate submission
  - actual apply only after candidate policy returns `apply`
- self-cognition updates no longer directly mutate durable state on first observation
- personality `slow_evolve()` still preserves Phase 17 guarantees:
  - snapshot before apply
  - drift detection after proposed long-term change
  - rollback restores prior long-term personality state
- candidate manager health is folded into existing runtime health instead of adding a new endpoint
- candidate HITL tasks reuse the existing `waiting_hitl -> /hitl/respond -> hitl_feedback` path

## Verification Completed
- targeted candidate/runtime regression suite:
  - `python -m pytest tests/test_evolution_pipeline.py tests/test_personality_evolver.py tests/test_relationship_memory.py tests/test_runtime_bootstrap.py`
  - result: `17 passed`
- full test suite:
  - `python -m pytest`
  - result: `82 passed`
- bytecode compile:
  - `python -m compileall app tests`

## Explicitly Not Done Yet
- no persistent candidate store beyond process memory
- no generic rollback engine for world-model candidates beyond:
  - journaled candidate revert state
  - existing superseded/conflicted memory trail behavior
- no configurable risk thresholds; Phase 18 uses fixed defaults from the implementation
- no user-facing governance UI for browsing or approving candidate history
- no unification yet between Phase 16 memory-confirmation evidence and Phase 18 candidate evidence pools
- conflict-heavy inferred memories still prefer the existing memory-confirmation gate before entering a high-risk evolution-candidate path

## Handoff Rule For Future Codex
- preserve the distinction between:
  - memory truth confirmation
  - evolution application approval
- do not reintroduce direct long-term writes from `CognitionUpdater` or `PersonalityEvolver.slow_evolve()` without passing through candidate policy
- keep candidate journal details stable; later phases should extend them, not replace them with ad hoc shapes
- if a future phase adds persistent candidate storage, preserve:
  - current dedupe-key semantics
  - current low/medium/high default thresholds unless intentionally migrated
- if future work deepens rollback behavior for world-model state, make candidate `reverted` status remain the control-plane truth for failed or rejected applications
- if future work expands HITL handling, continue routing `evolution_candidate` and `memory_confirmation` through distinct metadata keys so the handlers do not collapse into one ambiguous approval path
