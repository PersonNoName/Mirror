# Long-Term Companion Plan

## Purpose
- machine-oriented roadmap for post-Phase-15 companion evolution
- source of truth for long-term companionship and controlled self-evolution work
- optimize for future Codex execution, not human onboarding
- prefer phased execution; complete one phase before starting the next unless explicitly requested otherwise

## Read Order For Future Codex
1. `LONG_TERM_COMPANION_PLAN.md`
2. `OPTIMIZATION_PLAN.md`
3. `docs/phase_15_status.md`
4. `app/runtime/bootstrap.py`
5. relevant target files for the current phase only

## Current System Snapshot
- project status: `runtime-foundation-strong / companion-product-early / evolution-control-thin`
- current baseline:
  - runtime wiring exists and is centralized
  - synchronous dialogue path, async task dispatch, HITL loop, and degraded mode already form a usable local runtime
  - tests exist for core parsing, routing, bootstrap, task flow, observability, and local integration slices
- current strength:
  - subsystem boundaries are mostly clean
  - extension points already exist: tool/hook/agent/skill/mcp registries
  - memory, task, event, and runtime modules are present and wired
  - the system can already operate as an agent runtime with partial self-observation
- current weakness:
  - long-term companion behavior is still weak compared with runtime capability
  - memory structures are not yet explicit enough for relationship continuity
  - personality evolution is not yet controlled enough for stable companionship
  - emotional support policy, user memory governance, and dependency-safety boundaries are not yet first-class
- summary judgment:
  - the engineering foundation is formed
  - the companion product layer is still early
  - the next roadmap should prioritize relationship quality, memory quality, personality stability, and controlled evolution before expanding more execution power

## Global Rules
- do not sacrifice truthfulness or identity clarity in order to feel more human-like
- do not allow autonomous evolution to bypass auditability, rollback, or user control
- do not prioritize task execution expansion over the core companionship loop
- do not mix inferred memory and factual memory as equal truth sources
- preserve single-machine-first execution and incremental delivery
- preserve centralized runtime bootstrap in `app/runtime/bootstrap.py`
- preserve registry-based extension loading and avoid ad hoc direct-import extension patterns
- each phase must leave the app in a runnable state
- each phase should add verification, not only behavior
- prefer extending existing modules over introducing parallel systems with overlapping responsibility

## Hard Priorities
- P0:
  - relationship memory structure
  - personality stability controls
  - controlled evolution pipeline
- P1:
  - emotional understanding policy
  - relationship state modeling
  - user memory governance
- P2:
  - companion evaluation suite
  - gentle proactivity
  - safety and dependency boundaries

## Known Strategic Gaps
- repository-wide:
  - current architecture can act, remember, and evolve, but does not yet behave like a reliable long-term companion
- `app/memory/*`
  - memory is not yet explicitly separated into factual, inferred, and relationship-oriented truth classes
- `app/evolution/*`
  - evolution exists, but not yet as a controlled candidate pipeline with evidence thresholds and explicit rollback semantics
- `app/soul/*`
  - session adaptation and long-term personality boundaries are not yet sharp enough for stable relational identity
- `app/api/*`
  - no user-facing memory governance surface yet
- `app/runtime/bootstrap.py`
  - health and runtime summary do not yet expose personality versioning, evolution candidates, or rollback-related signals

---

## Phase 16 - Relationship Memory Foundation

### Goal
- establish memory structures that support long-term relational continuity rather than only retrieval convenience

### Why Now
- long-term companionship fails first at memory quality
- the runtime already has memory modules, but the memory model is not yet precise enough for stable relationship building

### Scope
- `app/memory/*`
- relevant evolution writers
- prompt-facing memory formatting where required

### Data / API Changes
- introduce explicit memory classes or schemas for:
  - factual memory
  - inferred memory
  - relationship memory
- each durable memory item must carry:
  - `source`
  - `confidence`
  - `updated_at`
  - `confirmed_by_user`

### Required Work
- define short-term, medium-term, and long-term memory responsibilities
- ensure inferred conclusions are stored separately from user-confirmed facts
- add memory conflict detection and conflict-resolution rules
- add a path for explicit memory confirmation requests before promoting sensitive or uncertain memories
- improve prompt-facing memory formatting so the foreground model can distinguish fact vs inference vs relationship history

### Acceptance
- memory items can be classified by truth type and time horizon
- conflicts between old and new memory can be represented intentionally instead of silent overwrite
- prompt-facing memory no longer treats all retrieved content as equal truth
- tests cover memory classification, conflict handling, and confirmation-related behavior

### Non-Goals
- no major storage backend replacement
- no broad product-surface expansion yet

---

## Phase 17 - Personality Stability And Session Adaptation

### Goal
- stabilize long-term identity while keeping session-level adaptation flexible and bounded

### Why Now
- a companion that changes too easily is less trustworthy than one that adapts slowly but coherently
- current personality and session adaptation behavior should be made structurally distinct before evolution is made more powerful

### Scope
- `app/memory/core_memory.py`
- `app/evolution/personality_evolver.py`
- prompt assembly paths that consume personality state

### Data / API Changes
- split personality state into:
  - core personality
  - relationship style
  - session adaptation
- add version and snapshot metadata for personality state

### Required Work
- define which fields are allowed to evolve and which are effectively stable
- prevent session adaptation from directly mutating long-term personality truth by default
- add personality snapshots and rollback support
- ensure prompt construction reflects the three-layer distinction cleanly
- introduce drift checks before applying large personality changes

### Acceptance
- session adaptation is explicitly short-term and bounded
- long-term personality changes are versioned and reversible
- prompt context distinguishes stable identity from temporary adaptation
- tests cover snapshot creation, rollback, and adaptation isolation

### Non-Goals
- no redesign of the entire prompt architecture
- no attempt to make personality maximally expressive yet

---

## Phase 18 - Controlled Evolution Pipeline

### Goal
- replace direct evolution writes with a candidate-based, evidence-backed, risk-aware pipeline

### Why Now
- uncontrolled self-modification is incompatible with reliable long-term companionship
- evolution needs explicit thresholds before product depth is expanded further

### Scope
- `app/evolution/*`
- journal and stability modules
- runtime health exposure where needed

### Data / API Changes
- evolution state must support at least:
  - `candidate`
  - `pending`
  - `applied`
  - `reverted`
- each candidate must record:
  - evidence summary
  - rationale
  - risk level
  - affected area

### Required Work
- route evolution proposals into a candidate pool instead of immediate durable mutation
- aggregate repeated evidence before applying medium- and high-impact changes
- define risk bands:
  - low risk: auto-apply
  - medium risk: delayed observation before apply
  - high risk: HITL and/or explicit audit gate
- add rollback semantics tied to personality and memory evolution outcomes
- expose candidate and rollback information through journal and health-oriented surfaces where useful

### Acceptance
- evolution no longer writes important state changes directly without candidate tracking
- risk-aware application behavior is explicit and testable
- rollback paths are defined for applied changes
- tests cover thresholding, candidate lifecycle, and audit trail integrity

### Non-Goals
- no distributed approval workflow
- no external governance service required

---

## Phase 19 - Emotional Understanding And Support Policy

### Goal
- make emotional understanding and support style explicit, testable, and safe

### Why Now
- long-term companionship quality depends more on emotional fit than on raw task power
- current system can reply, but emotional support policy is not yet first-class

### Scope
- foreground reasoning support paths
- relevant memory/evolution signals
- fallback and high-risk response policy

### Data / API Changes
- add structured emotional interpretation outputs for:
  - emotion class
  - intensity
  - duration hint
  - support preference when known

### Required Work
- distinguish listening-oriented responses from problem-solving-oriented responses
- track user support-style preferences when evidence is strong enough
- introduce high-risk emotional scenario handling rules and safe degraded behavior
- ensure emotional interpretations can be stored as inferred memory, not factual truth, unless confirmed
- add tests for support-policy routing and emotional-risk handling

### Acceptance
- emotional response style becomes intentional instead of implicit only
- high-risk emotional situations trigger constrained behavior
- support preference can influence future responses without being overstated as fact
- tests cover emotion interpretation, support-mode selection, and risk policies

### Non-Goals
- no claim of clinical or therapeutic capability
- no medicalization of normal companion behavior

---

## Phase 20 - Relationship State Machine

### Goal
- model relationship progression explicitly so behavior can evolve with trust, familiarity, and context

### Why Now
- a long-term companion should not behave the same way with a first-day user and a long-term user
- relationship-aware behavior should exist before proactive behavior is introduced

### Scope
- memory and evolution coordination
- companion policy and prompt conditioning

### Data / API Changes
- add relationship stages such as:
  - unfamiliar
  - trust-building
  - stable-companion
  - vulnerable-support
  - repair-and-recovery

### Required Work
- define stage transition rules based on interaction evidence rather than arbitrary counters alone
- use relationship stage to adjust:
  - proactive intensity
  - memory reference confidence
  - tone and boundary strength
- add structured support for long-term event continuity
- ensure state transitions are logged and reviewable

### Acceptance
- relationship stage becomes an explicit runtime concept
- stage changes influence behavior in bounded, testable ways
- long-term event continuity is easier to represent
- tests cover stage transitions and behavior differences by stage

### Non-Goals
- no anthropomorphic overclaiming
- no attempt to simulate human attachment mechanically

---

## Phase 21 - User Memory Governance

### Goal
- give the user meaningful visibility and control over what the companion stores and learns

### Why Now
- long-term trust requires user agency over durable memory and learning behavior
- governance must exist before proactivity and deeper evolution are expanded

### Scope
- API layer
- memory store interfaces
- journal and audit surfaces

### Data / API Changes
- add user-facing capabilities for:
  - list memory
  - correct memory
  - delete memory
  - block learning for selected content classes
- distinguish internal candidate memory from confirmed durable memory in external presentation

### Required Work
- define which memory classes are user-visible and how they should be presented safely
- add explicit correction and deletion flows
- define default retention and decay behavior for different memory classes
- ensure user governance events are journaled and respected by downstream evolution logic
- add tests for correction, deletion, learning-block, and confirmed-vs-candidate visibility

### Acceptance
- users can inspect and govern important durable memory
- system learning respects governance actions
- memory retention rules are explicit rather than accidental
- tests cover governance APIs and downstream enforcement

### Non-Goals
- no full admin dashboard required
- no cross-user multi-tenant policy layer required yet

---

## Phase 22 - Companion Evaluation Suite

### Goal
- create a durable evaluation layer for companion quality, consistency, and evolution safety

### Why Now
- long-term companion quality cannot be judged only by unit tests and infrastructure correctness
- future changes need companion-specific metrics and regression tests

### Scope
- `tests/`
- evaluation fixtures and scenario packs
- optional offline evaluation helpers

### Required Work
- define companion metrics such as:
  - memory accuracy
  - consistency
  - felt-understanding proxy
  - relationship continuity
  - mistaken-learning rate
  - drift rate
- build multi-session, multi-week, and multi-month simulated conversation evaluation slices
- add regression coverage for long-term evolution and rollback behavior
- keep evaluation runnable locally without requiring production infrastructure

### Acceptance
- companion quality can be evaluated across time, not only per request
- long-horizon regressions become visible
- tests or fixtures cover memory, drift, rollback, and continuity scenarios

### Non-Goals
- no requirement for a full benchmark platform
- no external telemetry dependency required

---

## Phase 23 - Gentle Proactivity

### Goal
- add low-intrusion proactive companionship without becoming mechanical or overbearing

### Why Now
- proactive follow-up should come after memory quality, relationship stage, and governance are in place
- otherwise the system risks noisy or inappropriate outreach

### Scope
- relationship policy
- scheduling or follow-up orchestration
- user preference enforcement

### Required Work
- define gentle proactivity triggers based on:
  - relationship stage
  - explicit user preference
  - topic importance
  - frequency limits
- prevent repetitive reminder-style behavior
- ensure proactive messages reference prior context accurately and conservatively
- add tests for trigger eligibility, throttling, and suppression behavior

### Acceptance
- proactive behavior is low-frequency, contextual, and bounded
- the system can follow up without feeling like a generic reminder bot
- tests cover throttling, stage gating, and preference handling

### Non-Goals
- no aggressive notification strategy
- no growth-oriented engagement optimization

---

## Phase 24 - Safety And Dependency Boundaries

### Goal
- enforce companion-specific safety boundaries around emotional dependency, manipulative language, and role overreach

### Why Now
- long-term companionship plus autonomous evolution creates risks that standard assistant safety coverage does not fully address
- safety boundaries should be explicit before deeper personalization scales

### Scope
- prompt policy
- evolution constraints
- audit and journal visibility
- high-risk response logic

### Required Work
- define and enforce rules against:
  - exclusivity framing
  - dependency reinforcement
  - manipulative emotional steering
  - overclaiming irreplaceable companionship
- add policy treatment for high-risk advice and relationship-binding language
- ensure high-risk companion behavior is auditable
- integrate these constraints into memory, evolution, and response policy rather than only prompt text
- add tests for dependency-risk expressions and high-risk safety enforcement

### Acceptance
- dependency and manipulation boundaries are explicit and testable
- high-risk language is constrained or blocked intentionally
- audit visibility exists for companion-specific safety events
- tests cover representative dependency-risk and boundary-overreach scenarios

### Non-Goals
- no attempt to solve every trust-and-safety problem in one phase
- no full policy platform rewrite

---

## Execution Policy For Future Codex
- default next phase: `Phase 16 - Relationship Memory Foundation`
- after each phase:
  - update or create a matching status doc under `docs/`
  - record what was completed, what degraded, what remains
  - run relevant verification
- if a phase reveals a blocker:
  - fix the blocker in the current phase if tightly coupled
  - otherwise create a new intermediate phase doc and stop expanding scope

## Definition Of Done For Any Companion Phase
- implementation completed
- relevant tests added or updated
- basic verification executed and reported
- no unrelated refactor drift
- status document updated
- companion-specific risks and assumptions documented when behavior changes

## Suggested Status File Names
- `docs/phase_16_status.md`
- `docs/phase_17_status.md`
- `docs/phase_18_status.md`
- `docs/phase_19_status.md`
- `docs/phase_20_status.md`
- `docs/phase_21_status.md`
- `docs/phase_22_status.md`
- `docs/phase_23_status.md`
- `docs/phase_24_status.md`

## Immediate Next Action
- start with `Phase 16 - Relationship Memory Foundation`
