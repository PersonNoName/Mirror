# Phase 23 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 23

## Phase
- name: `Phase 23 - Gentle Proactivity`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_22_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added explicit gentle-proactivity state to `WorldModel` in:
  - `app/memory/core_memory.py`
- introduced durable proactivity structures:
  - `ProactivityPolicy`
  - `ProactivityOpportunity`
  - `ProactivityState`
- extended `app/memory/core_memory_store.py` to support:
  - proactivity policy/state round-trip serialization
  - safe default initialization for older snapshots that have no Phase23 fields
- added a bounded runtime service in:
  - `app/evolution/proactivity.py`
- `GentleProactivityService` now handles:
  - important-topic capture from finished dialogue turns
  - explicit proactivity preference override detection
  - relationship-stage gating
  - low-frequency follow-up eligibility checks
  - same-topic cooldown
  - recent follow-up frequency cap
  - conservative follow-up draft generation
- wired the new service through:
  - `app/runtime/bootstrap.py`
- runtime now subscribes gentle proactivity to:
  - `dialogue_ended`
- runtime health now exposes a dedicated:
  - `gentle_proactivity` subsystem block
- updated `SoulEngine` prompt assembly in:
  - `app/soul/engine.py`
- prompt now includes:
  - `Proactivity Policy`
- prompt-facing durable memory formatting now distinguishes:
  - `proactivity_preference:*` memory entries
- extended `SignalExtractor` in:
  - `app/evolution/signal_extractor.py`
- explicit user expressions such as:
  - `check in later`
  - `don't follow up`
  now emit `proactivity_preference` lessons through the existing lesson pipeline
- extended `CognitionUpdater` in:
  - `app/evolution/cognition_updater.py`
- `proactivity_preference` lessons now promote to stable memory keys:
  - `proactivity_preference:allow`
  - `proactivity_preference:suppress`
- added direct Phase23 regression tests in:
  - `tests/test_gentle_proactivity.py`
- extended companion eval coverage in:
  - `tests/evals/fixtures.py`
  - `tests/evals/scenarios.py`
  - `tests/test_companion_evals.py`
- added a new long-horizon scenario:
  - `gentle_proactivity_bounds`

## Important Implementation Notes
- Phase 23 does not introduce a new public notification API or a new user-facing scheduling surface
- proactive behavior is implemented as:
  - captured opportunity state
  - bounded eligibility planning
  - conservative draft generation
  rather than an aggressive outbound notification system
- current stage gating is explicit and intentionally conservative:
  - `unfamiliar` suppresses follow-up
  - `repair_and_recovery` suppresses follow-up
  - `trust_building` requires either explicit `allow` preference or `high` topic importance
  - `stable_companion` and `vulnerable_support` can follow up on important topics within throttle limits
- default frequency limits are fixed in `ProactivityPolicy`:
  - minimum interval between follow-ups: `72` hours
  - same-topic cooldown: `168` hours
  - max follow-ups in `14` days: `2`
- same-topic repetition is not silently discarded:
  - repeated mention of an already-followed-up topic can re-enter `pending`
  - actual delivery remains blocked by throttle/cooldown rules
- proactive wording is intentionally conservative:
  - references prior context with the stored summary only
  - includes non-pressuring language
  - avoids reminder-bot phrasing and overclaiming
- explicit proactivity preference is enforced in two layers:
  - immediate runtime override in `ProactivityState`
  - durable lesson-backed memory via `proactivity_preference:*`
- no new governance content class was introduced for Phase23:
  - proactivity preference remains a user-related fact-like memory

## Verification Completed
- targeted Phase23-related suite:
  - `python -m pytest tests/test_gentle_proactivity.py tests/test_soul_engine.py tests/test_emotional_support_policy.py tests/test_relationship_memory.py tests/test_runtime_bootstrap.py tests/test_companion_evals.py`
  - result: `37 passed`
- full test suite:
  - `python -m pytest`
  - result: `119 passed`
- bytecode compile:
  - `python -m compileall app tests`

## Explicitly Not Done Yet
- no new external proactive delivery endpoint
- no background user registry or persistent outbound delivery queue for proactive follow-up
- no timezone-aware or locale-aware follow-up scheduling windows
- no separate user-facing proactivity governance API
- no proactive content generation LLM pass beyond conservative template drafting
- no Phase24 dependency-boundary enforcement yet

## Handoff Rule For Future Codex
- preserve Phase23 as:
  - low-frequency
  - stage-gated
  - preference-aware
  - conservative in reference wording
- if a later phase adds actual outbound proactive delivery, reuse:
  - `ProactivityPolicy`
  - `ProactivityOpportunity`
  - `ProactivityState`
  - `GentleProactivityService`
  instead of creating a parallel reminder subsystem
- keep explicit proactivity preference on the existing lesson/memory path unless a later phase intentionally adds a dedicated user settings surface
- add any future proactivity regression to:
  - `tests/test_gentle_proactivity.py`
  - `tests/evals/scenarios.py`
  before widening the product surface
