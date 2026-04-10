# Phase 1 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 1

## Phase
- name: `Phase 1 - decoupled interface layer`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- platform contracts implemented in `app/platform/base.py`
- provider contracts implemented in `app/providers/base.py`
- sub-agent base contract implemented in `app/agents/base.py`
- task data contracts implemented in `app/tasks/models.py`
- outbox event contract implemented in `app/infra/outbox.py`
- core memory contracts implemented in `app/memory/core_memory.py`
- evolution event contracts implemented in `app/evolution/event_bus.py`
- tool registry skeleton implemented in `app/tools/registry.py`
- hook registry skeleton implemented in `app/hooks/registry.py`
- package exports updated for direct Phase 1 validation imports

## Important Implementation Notes
- Phase 1 defines interfaces and shared data structures only
- no platform adapter implementation is included yet
- no provider registry or concrete model provider implementation is included yet
- no event bus transport implementation is included yet
- no Redis/PostgreSQL/Neo4j/Qdrant runtime integration is included yet
- `provider_type` expresses protocol family, not vendor identity
- `Task.status` explicitly includes `waiting_hitl`
- task Redis Streams compatibility fields are reserved in `Task`:
  - `dispatch_stream`
  - `consumer_group`
  - `delivery_token`
- `EventType` includes exactly 8 canonical event names for the async evolution pipeline
- hook execution is best-effort by contract: handler exceptions must be logged and swallowed

## Contract Surface Finalized In Phase 1
- platform:
  - `PlatformContext`
  - `InboundMessage`
  - `OutboundMessage`
  - `HitlRequest`
  - `PlatformAdapter`
- providers:
  - `ModelSpec`
  - `ChatModel`
  - `EmbeddingModel`
  - `RerankerModel`
- agents:
  - `SubAgent`
- tasks:
  - `Task`
  - `TaskResult`
  - `Lesson`
- memory:
  - `MemoryEntry`
  - `CapabilityEntry`
  - `BehavioralRule`
  - `SelfCognition`
  - `WorldModel`
  - `PersonalityState`
  - `TaskExperience`
  - `CoreMemory`
- evolution:
  - `EventType`
  - `Event`
  - `InteractionSignal`
  - `EvolutionEntry`
  - `EventBus`
- extension layer:
  - `ToolRegistry`
  - `tool_registry`
  - `HookPoint`
  - `HookRegistry`
  - `hook_registry`

## Verification Completed
- `python -m compileall app` succeeded
- Phase 1 import validation from `PLAN.md` succeeded
- smoke validation succeeded for:
  - dataclass instantiation
  - `HookPoint` values
  - `EventType.ALL`
  - `Task.status = waiting_hitl`
  - `tool_registry` import

## Files Relevant For Next Phases
- platform contracts:
  - `app/platform/base.py`
- provider contracts:
  - `app/providers/base.py`
- sub-agent contract:
  - `app/agents/base.py`
- task contracts:
  - `app/tasks/models.py`
- memory contracts:
  - `app/memory/core_memory.py`
- evolution contracts:
  - `app/evolution/event_bus.py`
- extension contracts:
  - `app/tools/registry.py`
  - `app/hooks/registry.py`

## Explicitly Not Done Yet
- `ModelProviderRegistry`
- concrete `PlatformAdapter` implementations
- any concrete `SubAgent`
- task store / blackboard / queue implementation
- core memory cache or persistence implementation
- event bus publish/subscribe transport implementation
- runtime hook loading or tool loading

## Handoff Rule For Future Codex
- assume Phase 1 is complete unless this file is updated otherwise
- preserve existing field names and package boundaries unless a later phase forces a schema migration
- future implementations must depend on these contracts instead of introducing parallel shapes
- avoid direct SDK coupling in business modules; route future model usage through provider abstractions
