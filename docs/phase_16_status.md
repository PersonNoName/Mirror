# Phase 16 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 16

## Phase
- name: `Phase 16 - Relationship Memory Foundation`
- status: `completed`
- implementation_basis:
  - `LONG_TERM_COMPANION_PLAN.md`
  - `docs/phase_15_status.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- introduced explicit durable memory schemas in:
  - `app/memory/core_memory.py`
- added truth-aware durable memory types:
  - `FactualMemory`
  - `InferredMemory`
  - `RelationshipMemory`
  - shared `DurableMemory` metadata contract
- added durable metadata required by Phase 16:
  - `source`
  - `confidence`
  - `updated_at`
  - `confirmed_by_user`
  - `truth_type`
  - `time_horizon`
  - `status`
  - `sensitivity`
- upgraded `WorldModel` from generic buckets to prompt-facing structured sections:
  - confirmed facts
  - inferred memory
  - relationship history
  - pending confirmations
  - memory conflicts
- kept backward compatibility for old core-memory snapshots by mapping legacy `MemoryEntry` world-model payloads into structured factual memory during load
- extended `GraphStore` relation persistence/query payloads to include truth/lifecycle metadata and preserve relation history instead of silently overwriting active edges
- extended `VectorRetriever` payloads so retrieved context carries truth/status metadata into the foreground model
- updated `CognitionUpdater` to:
  - classify lessons into fact vs inference vs relationship memory
  - route sensitive or low-confidence memories into `pending_confirmation`
  - create memory-confirmation HITL tasks using existing waiting-HITL flow
  - handle HITL approval/rejection feedback and promote or supersede pending memories
  - represent conflicts instead of silently overwriting confirmed memories
- updated `CoreMemoryScheduler` world-model rebuild/compression logic to preserve:
  - confirmed memories
  - pending confirmations
  - conflict summaries
  - relationship history from graph storage
- updated `SoulEngine` prompt formatting so foreground reasoning can distinguish:
  - confirmed facts
  - inferred memory
  - relationship history
  - pending confirmation
  - memory conflicts
- widened HITL decision validation to allow `defer` for memory confirmation flows
- added Phase 16 coverage in:
  - `tests/test_relationship_memory.py`
  - updated `tests/test_soul_engine.py`

## Important Implementation Notes
- Phase 16 stayed on the existing storage stack:
  - PostgreSQL snapshots unchanged at the backend choice level
  - Neo4j still backs relationship memory
  - Qdrant still backs retrieval
  - Redis/HITL flow unchanged at the transport level
- memory confirmation reuses the existing task + HITL mechanism instead of introducing a new product surface
- confirmation tasks are created from the evolution path and stored in task metadata under `memory_confirmation`
- HITL approval promotes pending memory into active structured memory; rejection preserves a conflict/superseded trail
- relationship memories are preserved historically in graph storage; active and superseded/conflicted records can coexist
- prompt formatting now marks retrieved context with truth/status tags so the foreground model no longer treats all retrieved content as equal truth
- fixed an existing corrupted implementation artifact in `app/evolution/personality_evolver.py` while completing this phase because it blocked reliable compilation

## Verification Completed
- `pytest`
  - result: `72 passed`
- `python -m compileall app tests`

## Explicitly Not Done Yet
- no dedicated user-facing memory management UI
- no memory-specific listing/query API beyond existing internal runtime usage
- no automatic client delivery path for background-created memory-confirmation requests beyond the reused HITL task/event plumbing
- no storage migration for normalizing historical graph edges already written without the new metadata
- no broad policy layer for sensitive-memory taxonomy beyond the current simple `details["sensitive"]` / confidence rules

## Handoff Rule For Future Codex
- preserve the separation between confirmed facts, inferred memories, and relationship memories; do not collapse them back into undifferentiated prompt text
- any future prompt or retrieval changes should keep truth/status markers visible to the foreground model
- if later phases expand confirmation UX, build on the current `memory_confirmation` HITL metadata contract instead of inventing a second confirmation path
- if later phases add richer memory extraction, update `tests/test_relationship_memory.py` and `tests/test_soul_engine.py` before broadening scope
