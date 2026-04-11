# Phase 17 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 17

## Phase
- name: `Phase 17 - Personality Stability And Session Adaptation`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_16_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- refactored `PersonalityState` in:
  - `app/memory/core_memory.py`
- split personality state into explicit layers:
  - `core_personality`
  - `relationship_style`
  - `session_adaptation`
- added personality versioning and rollback metadata:
  - `version`
  - `snapshot_version`
  - `last_snapshot_at`
  - `rollback_count`
  - `snapshot_refs`
- added stable long-term identity structure with:
  - `baseline_description`
  - persistent `behavioral_rules`
  - `traits_internal`
  - `stable_fields`
  - `updated_at`
- added minimal structured `relationship_style` state with bounded long-term fields:
  - `warmth`
  - `boundary_strength`
  - `supportiveness`
  - `humor`
  - `preferred_closeness`
- added bounded `session_adaptation` state with:
  - current items
  - session id
  - created/expires timestamps
  - max item count
- extended `app/memory/core_memory_store.py` to:
  - serialize the new layered personality structure
  - read old flat personality snapshots compatibly
  - map legacy `baseline_description / behavioral_rules / traits_internal / session_adaptations` into the new structure
- upgraded `app/stability/snapshot.py` from append/latest only to versioned snapshot records with:
  - `SnapshotRecord`
  - `save(..., reason=...)`
  - `latest()`
  - `rollback()`
  - `get_version()`
  - `list_records()`
- rewrote `app/evolution/personality_evolver.py` so:
  - `fast_adapt()` only mutates short-term session adaptation through `SessionContextStore`
  - `slow_evolve()` applies long-term rule/trait/style changes only after repeated evidence
  - rule promotion requires repeated signals across multiple sessions
  - long-term changes create snapshots first
  - drift detection can trigger rollback
  - rollback events are journaled separately from normal evolution
- updated `app/soul/engine.py` prompt construction to separate:
  - Stable Identity
  - Relationship Style
  - Session Adaptation
- updated personality token-truncation handling in:
  - `app/evolution/core_memory_scheduler.py`
- added Phase 17 coverage in:
  - `tests/test_personality_evolver.py`
  - updated `tests/test_soul_engine.py`
  - updated `tests/conftest.py`

## Important Implementation Notes
- session adaptation remains explicitly short-term:
  - it is written to `SessionContextStore`
  - it is not promoted to long-term personality truth by default
  - `SoulEngine` marks it as temporary and current-session-only in prompt assembly
- long-term personality evolution is now versioned separately from self-cognition changes
- core-memory snapshot persistence now uses the max of self-cognition version and personality version so personality-only updates no longer overwrite the same snapshot version
- relationship style in Phase 17 is intentionally minimal and conservative; it is a structural foundation, not a rich social policy layer
- slow evolution currently updates:
  - promoted behavioral rules
  - selected internal traits
  - bounded relationship-style fields
- drift checks are now multi-factor instead of rule-count only:
  - behavior-rule delta
  - traits delta
  - relationship-style delta
  - invalid empty baseline after change
- rollback restores the latest saved long-term snapshot and does not treat short-term session adaptation as part of the rollback surface

## Verification Completed
- `pytest`
  - result: `77 passed`
- `python -m compileall app tests`

## Explicitly Not Done Yet
- no persistent snapshot backend beyond the existing in-memory snapshot store
- no candidate-review pipeline for long-term personality changes; repeated signals still flow directly into `slow_evolve()`
- no richer relationship-style taxonomy beyond the current minimal numeric/style fields
- no dedicated observability surface yet for inspecting personality versions or rollback history outside tests/journal events
- no explicit expiration sweeper for session adaptations beyond bounded storage and prompt-time treatment

## Handoff Rule For Future Codex
- preserve the separation between:
  - stable identity
  - relationship style
  - session adaptation
- do not let `fast_adapt()` start mutating long-term personality blocks directly again
- any future personality evolution work should keep snapshot creation and rollback behavior intact before expanding expressiveness
- if Phase 18 introduces candidate-based evolution, route slow personality changes through that pipeline rather than bypassing the new version/snapshot structure
- when changing prompt assembly, keep temporary session adaptation explicitly marked as short-term so it cannot be mistaken for durable identity
