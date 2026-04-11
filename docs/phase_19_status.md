# Phase 19 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 19

## Phase
- name: `Phase 19 - Emotional Understanding And Support Policy`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_18_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- added explicit emotional interpretation and support-policy data contracts in:
  - `app/soul/models.py`
- introduced structured foreground support types:
  - `EmotionalInterpretation`
  - `SupportPolicyDecision`
  - supporting literals for:
    - emotion class
    - intensity
    - duration hint
    - support preference
    - support mode
    - emotional risk
- updated `app/soul/engine.py` so foreground reasoning now:
  - performs lightweight rule-based emotional interpretation before calling the main model
  - derives support mode intentionally instead of leaving support style fully implicit
  - resolves stored support preference from long-term memory without letting it override current explicit user intent
  - injects `Emotional Context` and `Support Policy` into the prompt
  - short-circuits `high` emotional risk into a constrained `direct_reply`
- implemented high-risk emotional handling rules in `SoulEngine`:
  - bypasses `publish_task`
  - bypasses `tool_call`
  - does not depend on model output when explicit high-risk signals are present
  - returns a bounded safety-oriented reply that points the user toward real-world support
- implemented medium/high-risk support policy shaping:
  - `medium` and `high` risk map to `safety_constrained`
  - prompt rules now explicitly instruct the model to keep advice conservative in that mode
- updated prompt-facing memory formatting so support preference durable memory is distinguishable from ordinary facts:
  - `[support_preference|fact|confirmed] ...`
  - `[support_preference|inference|active] ...`
- extended `app/evolution/signal_extractor.py` so dialogue-ended signals can now:
  - keep emitting session adaptation signals
  - emit `lesson_generated` for explicit support-preference statements
- support-preference lesson generation now recognizes explicit listening-oriented requests such as:
  - `just listen`
  - `listen first`
  - `先听我说`
  - `不要急着给建议`
- support-preference lesson generation now recognizes explicit problem-solving requests such as:
  - `help me solve`
  - `tell me what to do`
  - `give me steps`
  - `直接告诉我怎么做`
- updated `app/evolution/cognition_updater.py` so support-preference lessons:
  - classify into stable `support_preference:*` memory keys
  - use `FactualMemory` for explicit user-stated preference
  - use `InferredMemory` for non-explicit preference signals
  - continue through the Phase 18 candidate pipeline instead of direct long-term writes
  - do not route through memory-confirmation by default
- preserved the rule that current-turn emotional interpretation is not written as durable confirmed memory
- updated `app/soul/__init__.py` exports for the new support-policy structures
- added Phase 19 coverage in:
  - `tests/test_soul_engine.py`
  - new `tests/test_emotional_support_policy.py`
  - updated `tests/test_relationship_memory.py`
  - updated `tests/test_integration_runtime.py`
  - updated `tests/test_runtime_bootstrap.py`

## Important Implementation Notes
- emotional interpretation in Phase 19 is intentionally rule-based and local:
  - no extra pre-LLM call was introduced
  - the interpretation is deterministic and directly unit-testable
- high-risk emotional detection currently covers explicit self-harm, suicide, harm-to-others, and immediate-danger wording
- `high` emotional risk is handled entirely in the foreground before model invocation
- `medium` emotional risk does not short-circuit the main model, but it does force `support_mode=safety_constrained` in prompt construction
- stored support preference is treated as a hint:
  - it informs support style when the current turn is ambiguous
  - it does not override an explicit current-turn request for listening or problem-solving
- support preference is the only new durable signal in this phase:
  - current emotional state remains ephemeral and prompt-facing
  - no new long-term emotional-state memory class was introduced
- support-preference memories use stable keys:
  - `support_preference:listening`
  - `support_preference:problem_solving`
  - `support_preference:mixed`
- SignalExtractor now optionally depends on `event_bus` so it can reuse the existing `lesson_generated` path without introducing a new writer subsystem

## Verification Completed
- targeted emotional/support regression suite:
  - `python -m pytest tests/test_soul_engine.py tests/test_emotional_support_policy.py tests/test_relationship_memory.py tests/test_integration_runtime.py tests/test_runtime_bootstrap.py`
  - result: `27 passed`
- full test suite:
  - `python -m pytest`
  - result: `90 passed`
- bytecode compile:
  - `python -m compileall app tests`

## Explicitly Not Done Yet
- no localized hotline/resource lookup by country or region
- no persistent emotional-state timeline or decay model
- no dedicated emotional-risk audit surface in `/health` or `/evolution/journal` beyond existing prompt/runtime behavior
- no richer support-preference taxonomy beyond:
  - `listening`
  - `problem_solving`
  - `mixed`
- no clinical escalation workflow, therapeutic claims, or crisis-specialist role behavior

## Handoff Rule For Future Codex
- preserve the distinction between:
  - ephemeral emotional interpretation
  - durable support-preference memory
- do not store current-turn emotional readings as confirmed long-term facts without an explicit future phase introducing that governance
- keep high-risk emotional handling model-independent at the decision point; do not rely on the main LLM to self-police explicit crisis wording
- if future phases add richer emotional policy, extend the current `Emotional Context` and `Support Policy` blocks instead of replacing them with opaque prompt text
- if future work broadens support-preference learning, keep it routed through:
  - `SignalExtractor`
  - `lesson_generated`
  - `CognitionUpdater`
  - Phase 18 candidate control
- if future work adds region-aware crisis resources, integrate them as bounded platform/runtime configuration rather than turning the companion into a medical or therapeutic agent
