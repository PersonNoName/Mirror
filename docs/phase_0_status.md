# Phase 0 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 0

## Phase
- name: `Phase 0 - project scaffold`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- project scaffold created
- Python package root created at `app/`
- reserved module packages created:
  - `app/api`
  - `app/platform`
  - `app/providers`
  - `app/agents`
  - `app/tasks`
  - `app/memory`
  - `app/evolution`
  - `app/infra`
  - `app/tools`
  - `app/hooks`
  - `app/stability`
- `__init__.py` added for all reserved packages
- dependency manifest added in `requirements.txt`
- unified settings entry implemented in `app/config.py`
- FastAPI entry implemented in `app/main.py`
- logging bootstrap implemented in `app/logging.py`
- `.env.example` added with all required external service and model-routing keys
- PostgreSQL bootstrap migration added in `migrations/001_phase0_foundation.sql`
- Docker Compose stack added in `docker-compose.yml`

## Infra Implemented
- `postgres`
- `redis`
- `neo4j`
- `qdrant`
- `opencode`

## Important Implementation Notes
- `PostgreSQL` is treated as future source of truth
- `Redis` is treated as transport/cache only; no truth-state persistence assumptions
- config access must go through `app.config.settings`
- app entrypoint is `app.main:app`
- current phase intentionally contains no business logic
- no task execution logic
- no model provider implementation
- no platform adapter implementation
- no outbox relay implementation
- no event bus implementation

## Config Surface Finalized In Phase 0
- app:
  - `APP_NAME`
  - `APP_ENV`
  - `APP_HOST`
  - `APP_PORT`
  - `APP_LOG_LEVEL`
- postgres:
  - `POSTGRES_HOST`
  - `POSTGRES_PORT`
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`
  - `POSTGRES_DSN`
- redis:
  - `REDIS_HOST`
  - `REDIS_PORT`
  - `REDIS_DB`
  - `REDIS_PASSWORD`
  - `REDIS_URL`
- neo4j:
  - `NEO4J_URI`
  - `NEO4J_USER`
  - `NEO4J_PASSWORD`
  - `NEO4J_DATABASE`
- qdrant:
  - `QDRANT_HOST`
  - `QDRANT_PORT`
  - `QDRANT_GRPC_PORT`
  - `QDRANT_URL`
  - `QDRANT_API_KEY`
- opencode:
  - `OPENCODE_HOST`
  - `OPENCODE_PORT`
  - `OPENCODE_BASE_URL`
  - `OPENCODE_IMAGE`
- model routing:
  - `MODEL_REASONING_MAIN_*`
  - `MODEL_LITE_EXTRACTION_*`
  - `MODEL_RETRIEVAL_EMBEDDING_*`
  - `MODEL_RETRIEVAL_RERANKER_*`

## Database Objects Reserved
- `outbox_events`
  - fields present:
    - `id`
    - `topic`
    - `payload`
    - `status`
    - `retry_count`
    - `next_retry_at`
    - `created_at`
    - `published_at`
- `stream_consumers`
  - fields present:
    - `id`
    - `consumer_name`
    - `stream_name`
    - `group_name`
    - `last_heartbeat_at`
    - `last_delivered_id`
    - `pending_count`
    - `metadata`
    - `created_at`
    - `updated_at`
- `idempotency_keys`
  - fields present:
    - `id`
    - `scope`
    - `key`
    - `status`
    - `response_payload`
    - `expires_at`
    - `created_at`

## Verification Completed
- `python -m compileall app docker`
- `python -c "from app.config import settings; ..."` succeeded
- `python -c "from app.main import app; ..."` succeeded
- FastAPI health check succeeded at `GET /health`
- Docker Compose stack started successfully
- service health confirmed for:
  - `postgres`
  - `redis`
  - `neo4j`
  - `qdrant`
  - `opencode`

## Runtime Deviations From Original Plan
- `OpenCode` container is currently a Phase 0 placeholder service, not the real production OpenCode server
- reason:
  - configured public image `ghcr.io/sst/opencode:latest` was not pullable in current environment
- current placeholder files:
  - `docker/opencode-stub/Dockerfile`
  - `docker/opencode-stub/server.py`
- compatibility intent:
  - keep `OPENCODE_BASE_URL=http://127.0.0.1:4096`
  - allow Phase 5 replacement with real OpenCode without changing higher-level config naming
- `qdrant` is wrapped by `docker/qdrant-tools/Dockerfile` only to stabilize Compose health checks
- `neo4j` uses fresh Phase 0 volume names:
  - `neo4j_data_phase0`
  - `neo4j_logs_phase0`
- reason:
  - avoid incompatible existing local volume data from older Neo4j versions

## Files Relevant For Next Phases
- settings and config entry:
  - `app/config.py`
- app startup entry:
  - `app/main.py`
- logging:
  - `app/logging.py`
- infra compose:
  - `docker-compose.yml`
- env template:
  - `.env.example`
- base migration:
  - `migrations/001_phase0_foundation.sql`

## Explicitly Not Done Yet
- Phase 1 interface definitions
- `PlatformAdapter`
- `ModelProviderRegistry`
- `SubAgent` base classes
- task models
- core memory models
- event bus models
- tool registry
- hook registry
- any Redis Streams consumer groups or runtime consumers
- any PostgreSQL data access layer
- any Neo4j/Qdrant runtime integration

## Handoff Rule For Future Codex
- assume Phase 0 is complete unless this file is updated otherwise
- reuse existing config names and package layout
- do not rework scaffold unless required by a later phase blocker
- when implementing later phases, preserve:
  - `app.main:app`
  - `app.config.settings`
  - PostgreSQL truth-source assumption
  - Redis non-truth assumption
  - `OPENCODE_BASE_URL` compatibility contract
