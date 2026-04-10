# Phase 5 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 5

## Phase
- name: `Phase 5 - sub-agent execution`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- `CodeAgent` implemented in `app/agents/code_agent.py`
- `WebAgent` placeholder implemented in `app/agents/web_agent.py`
- Redis Streams task worker runtime implemented in `app/tasks/worker.py`
- task stream naming and consumer-group helpers added in `app/tasks/task_system.py`
- task persistence improved in `app/tasks/store.py` with PostgreSQL read/update support plus memory mirror
- startup wiring updated in `app/main.py` to register agents and launch workers
- Phase 5 status handoff document added

## Important Implementation Notes
- each agent uses its own stream suffix and consumer group:
  - `stream:task:dispatch:<agent>`
  - `stream:task:retry:<agent>`
  - `stream:task:dlq:<agent>`
- worker uses `XREADGROUP` for new messages and `XAUTOCLAIM` for pending recovery
- `CodeAgent` follows the documented OpenCode flow:
  - create session
  - send `prompt_async` with JSON schema
  - listen on `/global/event`
  - auto-approve low-risk permissions
  - escalate high-risk permissions through HITL wait
  - fetch structured output from `/session/{id}/message`
- current HITL implementation keeps the worker execution alive while waiting for user input; it does not yet persist a resumable remote session across process restart
- task completion and failure are pushed back to the web platform adapter for SSE subscribers

## Degradation Rules Finalized In Phase 5
- Redis unavailable:
  - worker manager stays idle
  - task dispatch remains recorded in outbox memory only
  - no async task execution occurs
- OpenCode unavailable:
  - `CodeAgent` task fails as retryable and can enter retry / DLQ flow
- PostgreSQL unavailable:
  - task state remains memory-backed, same as previous phases

## Verification Targets For This Phase
- `python -m compileall app`
- import validation for:
  - `CodeAgent`
  - `WebAgent`
  - `TaskWorker`
  - `TaskWorkerManager`
- worker startup path validation through `app.main`

## Explicitly Not Done Yet
- real browser / network agent loop in `WebAgent`
- durable remote-session resume after process restart during HITL pause
- Phase 6 evolution pipeline and event-stream persistence

## Handoff Rule For Future Codex
- assume Phase 5 worker runtime is the canonical async execution path unless this file is updated otherwise
- keep `TaskSystem -> OutboxRelay -> Redis Streams -> TaskWorker` boundaries intact
- do not bypass `AgentRegistry` when adding new sub-agents
