# Phase 14 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 14

## Phase
- name: `Phase 14 - API and product surface cleanup`
- status: `completed`
- implementation_basis:
  - `OPTIMIZATION_PLAN.md`
  - `docs/phase_13_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added explicit shared API response and error models in:
  - `app/api/models.py`
- tightened request validation for:
  - `/chat`
  - `/chat/stream`
  - `/hitl/respond`
- replaced raw dict success responses with typed response models for:
  - `/chat`
  - `/hitl/respond`
  - `/evolution/journal`
- standardized explicit API-layer error envelopes for:
  - `action_routing_failed`
  - `streaming_unavailable`
  - `task_not_found`
- narrowed `/chat` public payload:
  - user-facing reply fields stay top-level
  - internal task linkage moved behind `meta.task_id`
- kept `/chat/stream` path and SSE transport unchanged while clarifying:
  - `delta`
  - `message`
  - `done`
- added route-level contract tests in:
  - `tests/test_api_routes.py`

## Important Implementation Notes
- endpoint paths were preserved:
  - `/chat`
  - `/chat/stream`
  - `/hitl/respond`
  - `/evolution/journal`
- `/chat` now returns a narrower public contract:
  - `reply`
  - `session_id`
  - `user_id`
  - `status`
  - optional `meta.task_id`
- `/chat` no longer passes through raw router result dictionaries to clients
- `/chat` status is derived from internal action type:
  - direct reply and tool reply -> `completed`
  - async task dispatch -> `accepted`
  - HITL relay -> `waiting_hitl`
- `/chat/stream` keeps the existing SSE body format; Phase 14 only standardized unavailable-streaming error output
- FastAPI default `422` validation behavior was preserved for malformed input; explicit custom errors were added only for route-owned failure cases
- journal response is now typed and datetime serialization is delegated to Pydantic/FastAPI instead of hand-built string dicts

## Verification Completed
- `pytest`
  - result: `62 passed`
- `python -m compileall app tests`
- `python -c "from app.main import app; print(app.title)"`

## Explicitly Not Done Yet
- global exception middleware
- versioned API surface
- frontend-specific streaming protocol changes
- richer public metadata contracts for async task lifecycle
- authn/authz or per-user journal access policy

## Handoff Rule For Future Codex
- preserve the shared API error envelope unless a later phase intentionally versions the API
- keep `/chat` public payload user-facing; do not re-expose raw internal router/task dictionaries at top level
- keep `/chat/stream` as the existing SSE endpoint unless a later phase intentionally redesigns streaming
- prefer Phase 15 next unless the user explicitly requests another phase
