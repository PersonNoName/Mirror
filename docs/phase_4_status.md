# Phase 4 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 4

## Phase
- name: `Phase 4 - foreground reasoning path`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- foreground soul engine implemented in `app/soul/engine.py`
- action routing implemented in `app/soul/router.py`
- in-process runtime event bus implemented in `app/evolution/runtime_bus.py`
- web platform adapter implemented in `app/platform/web.py`
- agent registry implemented in `app/agents/registry.py`
- task store / task system / blackboard / outbox relay / monitor skeleton implemented in `app/tasks/`
- chat and hitl API routes implemented in `app/api/chat.py` and `app/api/hitl.py`
- FastAPI startup wiring updated in `app/main.py`
- task schema migration added in `migrations/003_phase4_tasks.sql`
- Phase 4 status handoff document added

## Important Implementation Notes
- `/chat` and `/chat/stream` are the first runnable conversation entrypoints
- current runtime uses graceful degradation instead of hard startup failure
- no model API key:
  - `SoulEngine` falls back to local `direct_reply`
- PostgreSQL unavailable:
  - task storage degrades to in-memory mode
  - core memory load failures fall back to empty `CoreMemory`
- Redis unavailable:
  - app still starts
  - session context falls back to null store
  - task dispatch relay becomes no-op
- `GET /chat/stream` is a session subscription endpoint, not the trigger request itself
- current `publish_task` path only reaches task skeleton and HITL/dispatch boundaries; no real worker execution is implemented yet

## Contract Surface Finalized In Phase 4
- soul:
  - `SoulEngine.run`
  - `Action`
  - `ActionRouter.route`
- platform:
  - `WebPlatformAdapter.subscribe`
  - `WebPlatformAdapter.unsubscribe`
  - `WebPlatformAdapter.send_outbound`
  - `WebPlatformAdapter.send_hitl`
- task runtime:
  - `TaskStore`
  - `TaskSystem`
  - `Blackboard`
  - `OutboxRelay`
  - `TaskMonitor`
- api:
  - `POST /chat`
  - `GET /chat/stream`
  - `POST /hitl/respond`

## Degradation Rules Finalized In Phase 4
- missing reasoning model credentials:
  - local fallback direct reply
- PostgreSQL task persistence unavailable:
  - in-memory `TaskStore`
- Redis unavailable:
  - no-op outbox relay
  - null session context store
- malformed model output:
  - `Action` falls back to `direct_reply`

## Verification Completed
- `python -m compileall app` succeeded
- direct route import validation succeeded for:
  - `SoulEngine`
  - `ActionRouter`
  - `WebPlatformAdapter`
  - `TaskSystem`
  - `Blackboard`
  - `agent_registry`
- local API smoke validation succeeded for:
  - `POST /chat`
  - `GET /chat/stream`
  - fallback direct reply without model API key

## Files Relevant For Next Phases
- soul runtime:
  - `app/soul/engine.py`
  - `app/soul/router.py`
- task runtime:
  - `app/tasks/store.py`
  - `app/tasks/task_system.py`
  - `app/tasks/blackboard.py`
  - `app/tasks/outbox_relay.py`
  - `app/tasks/monitor.py`
- platform and api:
  - `app/platform/web.py`
  - `app/api/chat.py`
  - `app/api/hitl.py`
- startup wiring:
  - `app/main.py`

## Explicitly Not Done Yet
- real tool execution
- real sub-agent worker consumption from Redis Streams
- production-grade persistent task resume after process restart
- real model-backed structured action generation verification with valid API key

## Handoff Rule For Future Codex
- assume Phase 4 is complete unless this file is updated otherwise
- preserve `/chat` and `/chat/stream` semantics
- keep graceful degradation unless a later phase intentionally promotes hard dependency requirements
- future task-worker phases should consume the existing task/outbox/blackboard boundaries instead of bypassing them
