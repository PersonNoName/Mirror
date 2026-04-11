# Phase 9 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 9

## Phase
- name: `Phase 9 - test foundation and safety net`
- status: `completed`
- implementation_basis:
  - `OPTIMIZATION_PLAN.md`
  - `docs/phase_8_status.md`
  - `main_agent_architecture_v3.4.md`
  - OpenCode server reference: `https://opencode.ai/docs/zh-cn/server/`

## Completed Scope
- added test runner dependencies to `requirements.txt`:
  - `pytest`
  - `pytest-asyncio`
- added repository test configuration in `pytest.ini`
- created `tests/` package with lightweight local-only fixtures and helpers
- added unit tests for:
  - `SoulEngine`
  - `ActionRouter`
  - `ToolRegistry.invoke`
  - `TaskSystem` HITL wait/response flow
  - `WebPlatformAdapter`
- added degraded-mode bootstrap smoke test for `bootstrap_runtime()`
- established local automated test entrypoint:
  - `pytest`

## Important Implementation Notes
- all Phase 9 tests are isolated from live Redis, PostgreSQL, Neo4j, Qdrant, and OpenCode
- runtime bootstrap coverage is implemented with monkeypatched constructors and stub components
- async tests use `pytest-asyncio` with `asyncio_mode = auto`
- pytest cache provider is disabled and `pytest-cache-files-*` directories are excluded from recursion to avoid local Windows permission noise in this workspace
- OpenCode server documentation was treated as compatibility context only; no OpenCode-dependent test was introduced in this phase

## Verification Completed
- `pytest`
  - result: `24 passed`
- `python -m compileall app tests`
- `python -c "from app.main import app; print(app.title)"`

## Explicitly Not Done Yet
- integration tests against live infra services
- end-to-end chat/task/HITL flow tests
- CI pipeline wiring
- runtime failure semantic hardening from Phase 10
- replacement of placeholder `WebAgent` behavior from Phase 12

## Handoff Rule For Future Codex
- treat `pytest` as the default local regression command
- extend existing test files before creating redundant new suites
- keep future tests local-first and dependency-free unless a later phase explicitly requires integration coverage
- prefer Phase 10 next unless the user explicitly requests another phase
