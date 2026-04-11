# Mirror Optimization Plan

## Purpose
- machine-oriented optimization backlog
- optimize for future Codex execution, not human onboarding
- root-level source of truth for post-Phase-7 improvements
- prefer phased execution; complete one phase before starting the next unless explicitly requested otherwise

## Read Order For Future Codex
1. `OPTIMIZATION_PLAN.md`
2. `docs/phase_7_status.md`
3. `app/runtime/bootstrap.py`
4. relevant target files for the current phase only

## Current System Snapshot
- project status: `architecture-strong / product-mid / quality-weak`
- current score baseline: `6.8/10`
- core strength:
  - runtime wiring is centralized
  - subsystem boundaries are mostly clean
  - extension points exist: tool/hook/agent/skill/mcp registries
  - degraded mode exists for multiple dependencies
- core weakness:
  - multiple user-facing and prompt-facing strings are mojibake / encoding-corrupted
  - no visible automated test suite
  - some subsystems are placeholders rather than real implementations
  - several failure paths are too silent or too optimistic

## Global Optimization Rules
- do not expand product scope before fixing correctness and quality debt
- prefer repair of existing architecture over architectural rewrite
- preserve centralized runtime bootstrap in `app/runtime/bootstrap.py`
- preserve registry-based extension loading; do not reintroduce ad hoc direct imports as the main extension mechanism
- every phase must leave the app in a runnable state
- every phase should add or improve verification, not only implementation
- avoid adding new non-ASCII content until encoding issues are fully normalized

## Hard Priorities
- P0:
  - encoding normalization
  - regression test foundation
  - failure-path correctness for task/event/runtime flow
- P1:
  - remove placeholder behavior in core user-visible flows
  - improve observability and health fidelity
- P2:
  - improve product capability depth
  - optimize retrieval / tool / async execution quality

## Known High-Risk Problems
- `app/soul/engine.py`
  - corrupted prompt text and fallback text
  - direct impact on model behavior quality
- `app/soul/router.py`
  - corrupted user-facing strings
  - tool-call parse errors and degraded replies are low quality
- `app/agents/code_agent.py`
  - corrupted schema descriptions and prompt text
  - capability heuristics depend on corrupted keywords
- `app/agents/web_agent.py`
  - current implementation is placeholder-only, not real web execution
- `app/evolution/event_bus.py`
  - handler exception path returns without explicit retry/poison handling strategy
- repository-wide
  - no visible `tests/` directory
  - no clear CI-level quality gate

---

## Phase 8 - Encoding And Text Integrity

### Goal
- remove all mojibake/corrupted strings from runtime-critical files
- ensure prompt text, user replies, HITL text, and keyword heuristics are semantically valid
- establish UTF-8-safe project conventions

### Scope
- inspect and normalize:
  - `app/soul/engine.py`
  - `app/soul/router.py`
  - `app/agents/code_agent.py`
  - `app/agents/web_agent.py`
  - any other files with corrupted literals discovered during search
- normalize root docs only if needed for future Codex execution
- do not rewrite business logic unless required by text repair

### Required Work
- replace corrupted literals with stable text
- prefer English for machine-facing prompts unless Chinese is explicitly required
- ensure capability keyword lists are valid strings
- ensure fallback replies are readable and consistent
- ensure JSON schema descriptions are valid strings
- add an explicit repository note that source files must be UTF-8

### Acceptance
- no obvious mojibake remains in runtime Python source
- `python -m compileall app` passes
- main app import still passes
- prompt-critical files are readable in plain text

### Non-Goals
- no product feature expansion
- no large refactor

---

## Phase 9 - Test Foundation And Safety Net

### Goal
- add the minimum automated test layer needed to safely continue iteration

### Scope
- create `tests/`
- add unit tests for:
  - `SoulEngine` action parsing and fallback behavior
  - `ActionRouter` tool-call parsing and routing behavior
  - `ToolRegistry.invoke`
  - `TaskSystem` HITL waiting/response path
  - `WebPlatformAdapter` SSE event fan-out basics
- add at least one degraded-mode runtime bootstrap smoke test with dependency stubs or monkeypatching

### Required Work
- choose a test runner and declare it in project dependencies if missing
- add a small fixture strategy; keep tests cheap and local
- isolate network/external services behind mocks
- verify corrupted-text regressions do not return

### Acceptance
- tests run locally with one command
- meaningful coverage exists for parsing/routing/degraded-mode core paths
- future Codex changes can extend tests instead of starting from zero

### Non-Goals
- no full end-to-end infra integration yet

---

## Phase 10 - Runtime Correctness And Failure Semantics

### Goal
- reduce silent failure, duplicate processing, and ambiguous state transitions

### Scope
- `app/evolution/event_bus.py`
- `app/tasks/worker.py`
- `app/tasks/outbox_relay.py`
- `app/runtime/bootstrap.py`
- related store/state modules if needed

### Required Work
- define explicit semantics for:
  - handler failure
  - retryable failure
  - terminal failure
  - duplicate delivery
  - degraded dependency startup
- improve event-bus exception handling so failure behavior is intentional, observable, and testable
- verify worker retry/DLQ transitions are coherent
- ensure health output reflects actual degraded capabilities
- fix any logic that always reports healthy/available when it should not

### Acceptance
- no major silent swallow remains on critical async paths without logging and intent
- retry/DLQ flow is deterministic
- health endpoint is more trustworthy
- tests cover at least the main failure semantics

### Non-Goals
- no major architecture rewrite of queueing model

---

## Phase 11 - Observability And Operator Clarity

### Goal
- make runtime behavior inspectable without reading code

### Scope
- structured logging improvements
- health payload improvements
- optional debug/status endpoints if lightweight

### Required Work
- add structured logs for:
  - task assignment
  - task retry
  - DLQ publish
  - event handler failure
  - degraded startup decisions
  - tool invocation failure
- enrich `/health` subsystem details with useful fields instead of binary status only
- document log event names briefly for future Codex use

### Acceptance
- a failed async path is visible from logs
- `/health` becomes operationally useful rather than mostly symbolic

### Non-Goals
- no external telemetry stack required

---

## Phase 12 - Replace Placeholder Capabilities

### Goal
- remove fake-complete behavior from user-visible execution paths

### Scope
- first target: `app/agents/web_agent.py`
- second target: any tool/hook examples currently pretending to be real capability

### Required Work
- choose one of:
  - implement a minimal real web lookup capability using an approved abstraction
  - or clearly downgrade/disable the web agent so it no longer pretends to perform real lookup
- capability scoring must match actual execution ability
- task completion messages must reflect reality, not placeholder success

### Acceptance
- no core agent reports fake success for work it did not perform
- blackboard assignment decisions are better aligned with actual agent capability

### Non-Goals
- no full autonomous browser agent unless explicitly requested later

---

## Phase 13 - Retrieval And Memory Quality

### Goal
- improve the usefulness and predictability of memory retrieval

### Scope
- `app/memory/vector_retriever.py`
- `app/memory/core_memory.py`
- related memory store and evolution writers

### Required Work
- validate retrieval ranking behavior
- add tests for namespace filtering, empty collection behavior, rerank merge behavior
- inspect whether rerank variance threshold is sensible
- ensure core memory and retrieval outputs are formatted for prompt usefulness rather than raw dataclass dumps

### Acceptance
- retrieval behavior is tested and predictable
- prompt context quality improves measurably at code level

### Non-Goals
- no large redesign of storage backends

---

## Phase 14 - API And Product Surface Cleanup

### Goal
- make the exposed API less prototype-like and easier to evolve

### Scope
- `app/api/chat.py`
- `app/api/hitl.py`
- `app/api/journal.py`
- platform models if needed

### Required Work
- validate request/response schemas more tightly
- clarify streaming behavior and availability
- separate internal reply metadata from user reply payload where useful
- ensure error responses are intentional and consistent

### Acceptance
- API behavior is more stable and explicit
- chat and HITL endpoints are easier to consume safely

### Non-Goals
- no frontend work required

---

## Phase 15 - Integration And End-to-End Confidence

### Goal
- prove that the main runtime path works across multiple subsystems together

### Scope
- startup
- `/chat`
- `/chat/stream`
- async task dispatch
- HITL response loop

### Required Work
- add a small integration test slice using local test doubles where possible
- if external services are required, keep the suite optional and clearly separated
- verify at least one happy path and one degraded path

### Acceptance
- future Codex can modify the system with integration feedback, not only unit feedback

### Non-Goals
- no full production deployment workflow required

---

## Execution Policy For Future Codex
- default next phase: `Phase 8`
- after each phase:
  - update or create a matching status doc under `docs/`
  - record what was completed, what degraded, what remains
  - run relevant verification
- if a phase reveals a blocker:
  - fix blocker in the current phase if tightly coupled
  - otherwise create a new intermediate phase doc and stop expanding scope

## Definition Of Done For Any Optimization Phase
- implementation completed
- relevant tests added or updated
- basic verification executed and reported
- no unrelated refactor drift
- status document updated

## Suggested Status File Names
- `docs/phase_8_status.md`
- `docs/phase_9_status.md`
- `docs/phase_10_status.md`
- `docs/phase_11_status.md`
- `docs/phase_12_status.md`
- `docs/phase_13_status.md`
- `docs/phase_14_status.md`
- `docs/phase_15_status.md`

## Immediate Next Action
- start with `Phase 8 - Encoding And Text Integrity`
