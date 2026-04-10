# Phase 2 Status

## Purpose
- machine-oriented progress record
- optimize for future Codex context loading
- source of truth for what is already implemented in Phase 2

## Phase
- name: `Phase 2 - model provider implementation`
- status: `completed`
- implementation_basis:
  - `PLAN.md`
  - `main_agent_architecture_v3.4.md`

## Completed Scope
- `openai_compatible` chat provider implemented in `app/providers/openai_compat.py`
- `openai_compatible` embedding provider implemented in `app/providers/openai_compat.py`
- HTTP reranker provider implemented in `app/providers/openai_compat.py`
- shared HTTP client / retry behavior implemented in `app/providers/openai_compat.py`
- `ModelProviderRegistry` implemented in `app/providers/registry.py`
- `build_routing_from_settings(settings)` implemented in `app/providers/registry.py`
- provider package exports updated for direct Phase 2 imports
- Phase 2 status handoff document added

## Important Implementation Notes
- all provider calls use `httpx.AsyncClient`; no vendor SDK is introduced
- `provider_type` remains protocol-family metadata, not vendor identity
- `ModelSpec.api_key_ref` is interpreted as a direct API key value in Phase 2
- `OpenAICompatibleChatModel.generate()` calls `POST /chat/completions`
- `OpenAICompatibleChatModel.stream()` uses SSE and filters `[DONE]`
- `OpenAICompatibleEmbeddingModel.embed()` calls `POST /embeddings` and auto-batches inputs
- reranker calls default to `POST /rerank` with `{model, query, documents}`
- retry scope is limited to network errors, timeouts, `429`, and `5xx`
- `provider_type=native` is currently supported only for `rerank`, reusing the same HTTP reranker client

## Contract Surface Finalized In Phase 2
- provider routing:
  - `ModelProviderRegistry`
  - `build_routing_from_settings`
- concrete providers:
  - `OpenAICompatibleChatModel`
  - `OpenAICompatibleEmbeddingModel`
  - `OpenAICompatibleRerankerModel`
  - `ProviderRequestError`
- fixed routing profiles from settings:
  - `reasoning.main`
  - `lite.extraction`
  - `retrieval.embedding`
  - `retrieval.reranker`

## Supported Provider Routes In Phase 2
- `openai_compatible + chat`
- `openai_compatible + embedding`
- `openai_compatible + rerank`
- `native + rerank`

## Verification Completed
- `python -m compileall app` succeeded
- Phase 2 import validation from `PLAN.md` succeeded
- smoke validation succeeded for:
  - `build_routing_from_settings(settings)` profile generation
  - `registry.chat('reasoning.main')`
  - `registry.embedding('retrieval.embedding')`
  - `registry.reranker('retrieval.reranker')`
  - capability mismatch failure path
  - unknown profile failure path

## Files Relevant For Next Phases
- concrete provider implementations:
  - `app/providers/openai_compat.py`
- registry and routing:
  - `app/providers/registry.py`
- provider interfaces:
  - `app/providers/base.py`

## Explicitly Not Done Yet
- `ollama` embedding implementation
- anthropic provider implementation
- fallback chain orchestration between multiple profiles
- global provider lifecycle shutdown hooks
- live API integration tests that require external credentials

## Handoff Rule For Future Codex
- assume Phase 2 is complete unless this file is updated otherwise
- future model usage must go through `ModelProviderRegistry`
- do not bypass routing by instantiating provider clients directly in business modules
- preserve the fixed four-profile routing contract unless a later phase intentionally expands it
