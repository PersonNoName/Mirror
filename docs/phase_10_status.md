# Phase 10 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 10

## Phase
- name: `Phase 10 - runtime correctness and failure semantics`
- status: `completed`
- implementation_basis:
  - `OPTIMIZATION_PLAN.md`
  - `docs/phase_9_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- hardened event bus failure behavior in `app/evolution/event_bus.py`
- corrected degraded relay semantics in `app/tasks/outbox_relay.py`
- preserved terminal task statuses in `app/tasks/worker.py`
- extended failure status handling in `app/tasks/blackboard.py`
- improved runtime health fidelity in `app/runtime/bootstrap.py`
- added targeted Phase 10 failure-semantic tests in:
  - `tests/test_failure_semantics.py`

## Important Implementation Notes
- event deserialization failure is now treated as terminal for that delivery:
  - log failure
  - ACK malformed message
  - avoid infinite retry on unreadable payload
- event handler failure is now treated as retryable:
  - log failure
  - do not ACK
  - do not mark idempotency as done
- idempotency claim/mark-done failures are now explicit:
  - log failure
  - leave message unacked for retry
- degraded `OutboxRelay` no longer marks events as published when Redis is unavailable
- `TaskWorker` now preserves `interrupted` and `cancelled` terminal statuses instead of collapsing them into `failed`
- `Blackboard.on_task_failed()` now accepts explicit terminal status and emits it in the failure event payload
- runtime health now includes:
  - `outbox_relay`
  - `session_context`
  - `startup_degraded_reasons`
- `bind_runtime_state()` now sets `streaming_disabled = True` when Redis is unavailable

## Degradation Rules Finalized In Phase 10
- malformed stream payload:
  - log and ACK
  - no retry because payload is not recoverable
- handler execution failure:
  - log and leave unacked
  - retry remains possible through stream recovery
- idempotency persistence failure:
  - log and leave unacked
  - completion is not acknowledged until bookkeeping succeeds
- relay without Redis:
  - log skipped publish
  - keep outbox event pending
- retryable worker failure:
  - task returns to `pending`
  - retry event is published
- interrupted/cancelled worker failure:
  - task terminal status is preserved
  - DLQ still receives the failure record

## Verification Completed
- `pytest`
  - result: `31 passed`
- `python -m compileall app tests`
- `python -c "from app.main import app; print(app.title)"`

## Explicitly Not Done Yet
- richer operator-facing structured logging from Phase 11
- per-failure retry limits or poison-message quarantine for event bus deliveries
- live integration validation against Redis Streams and PostgreSQL
- end-to-end async workflow tests

## Handoff Rule For Future Codex
- preserve the current malformed-vs-retryable distinction in stream processing
- do not reintroduce `streaming_disabled = False` when Redis is absent
- treat pending outbox records during Redis outage as intentional, not as a bug
- prefer Phase 11 next unless the user explicitly requests another phase
