# Phase 6 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 6

## Phase
- name: `Phase 6 - async evolution layer`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- Redis Streams event bus implemented in `app/evolution/event_bus.py`
- PostgreSQL-backed outbox store implemented in `app/infra/outbox_store.py`
- relay upgraded to persistent outbox publishing in `app/tasks/outbox_relay.py`
- evolution pipeline added:
  - `SignalExtractor`
  - `ObserverEngine`
  - `MetaCognitionReflector`
  - `CognitionUpdater`
  - `PersonalityEvolver`
  - `CoreMemoryScheduler`
  - `EvolutionJournal`
  - `EvolutionScheduler`
- stability helpers added:
  - async circuit breaker
  - idempotency store
  - personality snapshot store
- journal API added at `GET /evolution/journal`
- startup wiring updated in `app/main.py`
- Phase 6 schema migration added

## Important Implementation Notes
- foreground emits now flow through persistent outbox before Redis Streams delivery
- event streams are split by intent:
  - `stream:event:dialogue`
  - `stream:event:task_result`
  - `stream:event:evolution`
  - `stream:event:low_priority`
- current V1 observer and reflector use `lite.extraction` when available; when unavailable they fail closed without blocking foreground
- `PersonalityEvolver.fast_adapt()` writes session adaptations to `SessionContextStore`
- `SoulEngine` now merges live session adaptations into prompt assembly
- `CoreMemoryScheduler` is the only intended write entrypoint for core-memory block updates

## Degradation Rules Finalized In Phase 6
- Redis unavailable:
  - event bus stays degraded
  - evolution consumers do not run
  - foreground still starts
- PostgreSQL unavailable:
  - outbox / journal / durable snapshot writes degrade to memory or no-op
  - foreground still starts
- lite extraction model unavailable:
  - observer / reflector / compression silently skip model-backed work

## Explicitly Not Done Yet
- production-grade world-model synthesis beyond current relation summary approach
- advanced nightly scheduling policy composition
- durable personality snapshot persistence across process restart
- complex entity merge / alias governance

## Handoff Rule For Future Codex
- assume Phase 6 event transport is PostgreSQL outbox + Redis Streams unless this file is updated otherwise
- keep core-memory writes behind `CoreMemoryScheduler`
- do not reintroduce direct `xadd` or direct foreground-to-evolution calls
