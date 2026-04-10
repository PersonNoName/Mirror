# Phase 7 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 7

## Phase
- name: `Phase 7 - extension registry and integration`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- runtime bootstrap extracted to `app/runtime/bootstrap.py`
- `app/main.py` reduced to FastAPI entrypoint plus aggregated `/health`
- `ToolRegistry` upgraded to structured register/describe/invoke contract
- `HookRegistry` upgraded with source-aware registrations
- `AgentRegistry` upgraded with source metadata and overwrite control
- hook trigger points wired into:
  - `SoulEngine.run`
  - `ActionRouter.route`
- `tool_call` path now executes via `ToolRegistry.invoke()`
- built-in example tool registration added in `app/tools/builtin_tools.py`
- local skill loader added in `app/skills/loader.py`
- minimal MCP loader/forwarder added in `app/tools/mcp_adapter.py`
- startup scripts added:
  - `start.sh`
  - `start.ps1`
- local sample skill manifest added under `skills/`

## Important Implementation Notes
- startup order is now centralized in bootstrap instead of `app/main.py`
- health response preserves top-level `status` and adds subsystem snapshots
- MCP integration is V1-minimal:
  - reads local config
  - loads remote `tools/list`
  - forwards `tools/call`
  - isolates per-server failures
- skill loader supports local manifests for:
  - `tool`
  - `hook`
  - `sub_agent`
- `tool_call` expects JSON content shaped as:
  - `{"name": "...", "arguments": {...}}`

## Degradation Rules Finalized In Phase 7
- missing `skills/` directory:
  - loader reports skipped
  - app still starts
- invalid skill manifest:
  - manifest is skipped with failure summary
  - other manifests still load
- invalid or unreachable MCP server:
  - that server is marked failed
  - app still starts
- tool invocation failure:
  - action router degrades to explanatory direct reply

## Explicitly Not Done Yet
- advanced MCP auth/session negotiation
- multi-step tool planning loop
- remote skill marketplace or hot reload
- dynamic worker refresh after post-start agent registration

## Handoff Rule For Future Codex
- keep new extension points behind registries and loaders; do not reintroduce direct core-file edits for new tools
- preserve `ToolRegistry.invoke()` as the single foreground tool execution path
- preserve bootstrap as the canonical startup wiring surface unless this file is updated otherwise
