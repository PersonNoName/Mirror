# Phase 21 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 21

## Phase
- name: `Phase 21 - User Memory Governance`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_20_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added explicit user memory governance state to `WorldModel` in:
  - `app/memory/core_memory.py`
- introduced `MemoryGovernancePolicy` with:
  - `blocked_content_classes`
  - `retention_days`
  - `updated_at`
- fixed governance content-class labels to:
  - `fact`
  - `inference`
  - `relationship`
  - `support_preference`
- added default retention policy for:
  - facts
  - relationships
  - inferences
  - pending confirmations
  - memory conflicts
  - world-model candidates
- updated `app/memory/core_memory_store.py` so:
  - new `memory_governance` snapshots round-trip correctly
  - legacy world-model snapshots load a safe default policy
- added `app/memory/governance.py`
- implemented `MemoryGovernanceService` that now:
  - lists user-visible world-model memory
  - distinguishes `durable` vs `candidate` visibility
  - corrects memory through audited replacement instead of in-place overwrite
  - deletes memory through governance metadata plus downstream candidate rollback
  - blocks future learning for selected content classes
  - prunes expired inference/pending/conflict/candidate entries
  - writes governance events into the evolution journal
- added user-facing governance API in:
  - `app/api/memory.py`
- added API routes:
  - `GET /memory`
  - `POST /memory/correct`
  - `POST /memory/delete`
  - `POST /memory/governance/block`
  - `GET /memory/governance`
- updated `app/api/models.py` with:
  - memory item response models
  - governance policy response models
  - correction/delete/block request models
- updated `app/api/__init__.py` and `app/main.py` to register the new memory router
- extended `app/evolution/candidate_pipeline.py` with read-only candidate listing to support governance visibility and rollback
- updated `app/evolution/cognition_updater.py` so:
  - blocked content classes are checked before world-model candidate creation
  - blocked lessons do not create pending confirmation placeholders or candidates
- updated `app/evolution/core_memory_scheduler.py` so:
  - world-model writes prune governed memory before snapshot rebuild
  - compressed world-model snapshots preserve `memory_governance`
- updated `app/memory/graph_store.py` with relationship supersede support for governance delete/correct flows
- updated runtime wiring in:
  - `app/runtime/bootstrap.py`
  - runtime now exposes `memory_governance_service`
  - `/health` now reports:
    - `memory_governance_enabled`
    - `memory_governance_degraded`

## Important Implementation Notes
- Phase 21 governance is intentionally limited to user-related world-model memory:
  - `confirmed_facts`
  - `inferred_memories`
  - `relationship_history`
  - `pending_confirmations`
  - `memory_conflicts`
- governance does not expose or allow direct user editing of:
  - `self_cognition`
  - `personality`
  - `relationship_style`
- correction semantics are explicit:
  - original item is superseded
  - replacement item becomes user-confirmed truth
  - replacement uses `source="user_correction"`
- deletion semantics are bounded:
  - durable memory is marked with governance metadata
  - prompt/API default visibility excludes deleted content after prune
  - matching world-model candidates are reverted with governance rollback reasons
- learning block semantics only affect future learning and pending candidates:
  - existing durable memory is preserved unless separately corrected or deleted
- retention/decay is implemented as:
  - read-time filtering in `/memory`
  - write-time pruning through `CoreMemoryScheduler`
- candidate visibility is intentionally restricted to:
  - `affected_area="world_model"`
  - `status in {"candidate", "pending"}`

## Verification Completed
- targeted Phase 21 regression suite:
  - `python -m pytest tests/test_api_routes.py tests/test_memory_governance.py tests/test_relationship_memory.py tests/test_runtime_bootstrap.py tests/test_failure_semantics.py tests/test_observability.py tests/test_integration_runtime.py`
  - result: `46 passed`
- full test suite:
  - `python -m pytest`
  - result: `105 passed`
- bytecode compile:
  - `python -m compileall app tests`

## Explicitly Not Done Yet
- no user-visible dashboard or admin UI for memory governance
- no bulk export/import governance workflow
- no governance controls for personality, self-cognition, or relationship-style state
- no background pruning scheduler beyond read/write-path enforcement
- no multi-tenant or org-wide governance policy layer

## Handoff Rule For Future Codex
- keep user governance scoped to world-model memory unless a later phase explicitly broadens that boundary
- do not expose `self_cognition` or long-term personality state through `/memory` without a separate governance design
- preserve the distinction between:
  - `visibility="durable"`
  - `visibility="candidate"`
- future governance work must continue to:
  - respect candidate rollback
  - write audit events into `/evolution/journal`
  - avoid silent in-place truth mutation
- if later phases add richer retention policies, extend the existing `MemoryGovernancePolicy` block instead of creating a parallel per-endpoint retention mechanism
