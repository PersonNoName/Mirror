# Phase 8 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 8

## Phase
- name: `Phase 8 - encoding and text integrity`
- status: `completed`
- implementation_basis:
  - `OPTIMIZATION_PLAN.md`
  - `main_agent_architecture_v3.4.md`
  - `docs/phase_7_status.md`
  - OpenCode server reference: `https://opencode.ai/docs/zh-cn/server/`

## Completed Scope
- normalized prompt-critical text in:
  - `app/soul/engine.py`
  - `app/soul/router.py`
  - `app/agents/code_agent.py`
  - `app/agents/web_agent.py`
- normalized async task notification text in:
  - `app/tasks/worker.py`
- replaced mojibake/corrupted literals with stable readable text
- converted machine-facing prompt content in `SoulEngine` to stable English
- repaired `CodeAgent` schema descriptions and task prompt text
- repaired `CodeAgent` capability keyword heuristics using valid bilingual keywords
- repaired `WebAgent` capability keyword heuristics using valid bilingual keywords
- added repository-wide encoding note:
  - `SOURCE_ENCODING.md`

## Important Implementation Notes
- Phase 8 intentionally focused on text integrity, not feature expansion
- user-visible strings were normalized to stable English where that reduced encoding risk
- machine-facing prompts now prefer English to reduce future encoding regressions
- `CodeAgent` OpenCode route usage was preserved during normalization:
  - `POST /session`
  - `POST /session/{id}/prompt_async`
  - `GET /global/event`
  - `GET /session/{id}/message`
  - `POST /session/{id}/permissions/{permission_id}`
  - `DELETE /session/{id}`
- OpenCode reference was used as a compatibility check, not as a reason to expand agent behavior in this phase

## Degradation Rules Finalized In Phase 8
- if reasoning model API key is missing:
  - `SoulEngine` returns a stable fallback direct reply
- if tool-call payload is malformed:
  - `ActionRouter` returns a readable fallback explanation
- if placeholder web execution is selected:
  - `WebAgent` now reports placeholder status explicitly instead of corrupted fake-success text

## Verification Completed
- `python -m compileall app`
- `python -c "from app.main import app; print(app.title)"`
- repository scan for common mojibake markers in `app/**/*.py` returned no matches after the Phase 8 edits

## Explicitly Not Done Yet
- full repository-wide normalization of corrupted legacy planning documents
- replacement of placeholder `WebAgent` with real web execution
- runtime failure semantics hardening for event bus and worker retry paths
- automated tests

## Handoff Rule For Future Codex
- treat `SOURCE_ENCODING.md` as the repository encoding rule
- prefer Phase 9 next unless the user explicitly requests another phase
- do not reintroduce non-UTF-8 text or copy damaged literals from older documents back into runtime code
