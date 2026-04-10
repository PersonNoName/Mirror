# Phase 3 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 3

## Phase
- name: `Phase 3 - memory system`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- PostgreSQL core memory snapshot schema added in `migrations/002_phase3_memory.sql`
- PostgreSQL-backed `CoreMemoryStore` implemented in `app/memory/core_memory_store.py`
- per-user in-process `CoreMemoryCache` implemented in `app/memory/core_memory.py`
- Redis-backed `SessionContextStore` implemented in `app/memory/session_context.py`
- Qdrant-backed `VectorRetriever` implemented in `app/memory/vector_retriever.py`
- Neo4j-backed `GraphStore` implemented in `app/memory/graph_store.py`
- memory package exports updated for direct Phase 3 imports
- Phase 3 status handoff document added

## Important Implementation Notes
- PostgreSQL is the durable source of truth for `CoreMemory` snapshots
- Redis is used only for session context storage and optional core-memory invalidation broadcast
- Qdrant stores semantic memory fragments for ANN retrieval
- Neo4j stores durable relation facts for user/world graph memory
- `CoreMemoryCache` is per-user and uses lazy load on first access
- `CoreMemoryCache.invalidate(user_id)` reloads from `CoreMemoryStore`
- session context is intentionally not persisted to PostgreSQL
- vector payload isolation is enforced with `user_id` and optional `namespace` filters
- graph relation types are restricted to the architecture word list:
  - `PREFERS`
  - `DISLIKES`
  - `USES`
  - `KNOWS`
  - `HAS_CONSTRAINT`
  - `IS_GOOD_AT`
  - `IS_WEAK_AT`

## Contract Surface Finalized In Phase 3
- core memory storage:
  - `CoreMemoryStore.load_latest`
  - `CoreMemoryStore.save_snapshot`
  - `CoreMemoryStore.list_snapshots`
- core memory cache:
  - `CoreMemoryCache.get`
  - `CoreMemoryCache.set`
  - `CoreMemoryCache.invalidate`
  - `CoreMemoryCache.mark_session_active`
  - `CoreMemoryCache.mark_session_inactive`
- session context:
  - `SessionContextStore.append_message`
  - `SessionContextStore.get_recent_messages`
  - `SessionContextStore.set_adaptations`
  - `SessionContextStore.get_adaptations`
  - `SessionContextStore.clear_session`
- vector retrieval:
  - `VectorRetriever.upsert`
  - `VectorRetriever.retrieve`
- graph storage:
  - `GraphStore.upsert_relation`
  - `GraphStore.get_relation`
  - `GraphStore.query_relations_by_user`
  - `GraphStore.build_world_model_summary`

## Backing Store Roles Finalized In Phase 3
- PostgreSQL:
  - durable `CoreMemory` snapshots
- Redis:
  - session raw context
  - session adaptations
  - optional core-memory invalidation broadcast
- Qdrant:
  - semantic vector memory retrieval
- Neo4j:
  - durable user/world relationship graph

## Verification Completed
- `python -m compileall app` succeeded
- Phase 3 cache/store validation from `PLAN.md` succeeded
- integration smoke validation succeeded for:
  - PostgreSQL snapshot save/load/list
  - Redis session context append/read/clear
  - Qdrant vector upsert/retrieve with isolated payload filters
  - Neo4j relation upsert/query/summary

## Files Relevant For Next Phases
- memory contracts and cache:
  - `app/memory/core_memory.py`
- durable snapshot store:
  - `app/memory/core_memory_store.py`
- session cache:
  - `app/memory/session_context.py`
- vector retrieval:
  - `app/memory/vector_retriever.py`
- graph storage:
  - `app/memory/graph_store.py`
- schema:
  - `migrations/002_phase3_memory.sql`

## Explicitly Not Done Yet
- world-model snapshot rebuild scheduler
- automatic graph-to-core-memory snapshot synthesis
- Redis pub/sub invalidation subscriber loop
- LRU retrieval cache mentioned in architecture `Level 1`
- long-term eviction and compression policies for vector memory

## Handoff Rule For Future Codex
- assume Phase 3 is complete unless this file is updated otherwise
- preserve PostgreSQL-as-truth and Redis-as-cache separation
- future reasoning code should read durable memory through `CoreMemoryCache` and retrieval services, not direct raw store calls
- future evolution code may write graph/vector/snapshot stores independently, but must preserve `user_id` isolation on every backend
