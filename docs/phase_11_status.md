# Phase 11 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 11

## Phase
- name: `Phase 11 - observability and operator clarity`
- status: `completed`
- implementation_basis:
  - `OPTIMIZATION_PLAN.md`
  - `docs/phase_10_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added structured runtime logs for:
  - task assignment
  - task retry scheduling
  - task DLQ publication
  - outbox publish success
  - outbox degraded publish skip
  - outbox relay retry scheduling
  - event bus degraded startup
  - event handler failure
  - runtime startup degraded summary
  - tool invocation failure
- enriched `RuntimeContext.health_snapshot()` for operator use
- kept `/health` as the only public ops surface
- added observability-focused tests in:
  - `tests/test_observability.py`

## Important Implementation Notes
- existing JSON `structlog` configuration was preserved; Phase 11 only expanded emitted events and health details
- `/health` remains backward compatible:
  - top-level `status` preserved
  - `subsystems` preserved
  - enrichment happened inside subsystem payloads plus top-level `streaming_available`
- subsystem health now includes reason fields where runtime knows the degraded cause
- worker health now includes:
  - `workers`
  - `degraded_workers`
- skill and MCP loader health now includes:
  - `loaded_count`
  - `skipped_count`
  - `failed_count`
- streaming operator signal is now explicit at health level through:
  - `streaming_available`

## Log Event Names Introduced In Phase 11
- `task_assigned`
- `task_retry_scheduled`
- `task_dlq_published`
- `outbox_relay_published`
- `outbox_relay_retry_scheduled`
- `outbox_relay_publish_skipped`
- `runtime_startup_degraded`
- `tool_invocation_failed`

## Verification Completed
- `pytest`
  - result: `37 passed`
- `python -m compileall app tests`
- `python -c "from app.main import app; print(app.title)"`

## Explicitly Not Done Yet
- external telemetry integration
- dedicated metrics endpoint
- richer per-subsystem live counters or queue depths
- operator-specific debug/status endpoints beyond `/health`
- alerting or persistence of log events

## Handoff Rule For Future Codex
- preserve the current structured log event names unless there is a compatibility reason to rename them
- enrich `/health` additively; do not remove `status`, `subsystems`, or `startup_degraded_reasons`
- prefer Phase 12 next unless the user explicitly requests another phase
