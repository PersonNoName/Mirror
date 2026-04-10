"""Model provider registry and settings-based routing."""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.providers.base import ChatModel, EmbeddingModel, ModelSpec, RerankerModel
from app.providers.openai_compat import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    OpenAICompatibleRerankerModel,
)


class ModelProviderRegistry:
    """Resolve model profiles to lazily instantiated provider clients."""

    def __init__(self, specs: dict[str, ModelSpec]) -> None:
        self.specs = specs
        self._instances: dict[tuple[str, str, str], Any] = {}

    def chat(self, profile: str) -> ChatModel:
        spec = self._get_spec(profile)
        if spec.capability != "chat":
            raise ValueError(f"profile '{profile}' does not provide chat capability")
        return self._get_or_create(spec)

    def embedding(self, profile: str) -> EmbeddingModel:
        spec = self._get_spec(profile)
        if spec.capability != "embedding":
            raise ValueError(f"profile '{profile}' does not provide embedding capability")
        return self._get_or_create(spec)

    def reranker(self, profile: str) -> RerankerModel:
        spec = self._get_spec(profile)
        if spec.capability != "rerank":
            raise ValueError(f"profile '{profile}' does not provide rerank capability")
        return self._get_or_create(spec)

    def _get_spec(self, profile: str) -> ModelSpec:
        try:
            return self.specs[profile]
        except KeyError as exc:
            raise KeyError(f"unknown model profile: {profile}") from exc

    def _get_or_create(self, spec: ModelSpec) -> Any:
        cache_key = (spec.provider_type, spec.capability, spec.profile)
        if cache_key not in self._instances:
            self._instances[cache_key] = self._build_provider(spec)
        return self._instances[cache_key]

    @staticmethod
    def _build_provider(spec: ModelSpec) -> Any:
        if spec.provider_type == "openai_compatible":
            if spec.capability == "chat":
                return OpenAICompatibleChatModel(spec)
            if spec.capability == "embedding":
                return OpenAICompatibleEmbeddingModel(spec)
            if spec.capability == "rerank":
                return OpenAICompatibleRerankerModel(spec)
        if spec.provider_type == "native" and spec.capability == "rerank":
            return OpenAICompatibleRerankerModel(spec)
        raise NotImplementedError(
            f"unsupported provider route: provider_type={spec.provider_type}, "
            f"capability={spec.capability}"
        )


def build_routing_from_settings(settings: Settings) -> dict[str, ModelSpec]:
    """Build the canonical Phase 2 routing table from application settings."""

    return {
        "reasoning.main": ModelSpec(
            profile="reasoning.main",
            capability="chat",
            provider_type=settings.model_routing.reasoning_main.provider_type,
            vendor=settings.model_routing.reasoning_main.vendor,
            model=settings.model_routing.reasoning_main.model,
            base_url=settings.model_routing.reasoning_main.base_url,
            api_key_ref=settings.model_routing.reasoning_main.api_key or None,
        ),
        "lite.extraction": ModelSpec(
            profile="lite.extraction",
            capability="chat",
            provider_type=settings.model_routing.lite_extraction.provider_type,
            vendor=settings.model_routing.lite_extraction.vendor,
            model=settings.model_routing.lite_extraction.model,
            base_url=settings.model_routing.lite_extraction.base_url,
            api_key_ref=settings.model_routing.lite_extraction.api_key or None,
        ),
        "retrieval.embedding": ModelSpec(
            profile="retrieval.embedding",
            capability="embedding",
            provider_type=settings.model_routing.retrieval_embedding.provider_type,
            vendor=settings.model_routing.retrieval_embedding.vendor,
            model=settings.model_routing.retrieval_embedding.model,
            base_url=settings.model_routing.retrieval_embedding.base_url,
            api_key_ref=settings.model_routing.retrieval_embedding.api_key or None,
        ),
        "retrieval.reranker": ModelSpec(
            profile="retrieval.reranker",
            capability="rerank",
            provider_type=settings.model_routing.retrieval_reranker.provider_type,
            vendor=settings.model_routing.retrieval_reranker.vendor,
            model=settings.model_routing.retrieval_reranker.model,
            base_url=settings.model_routing.retrieval_reranker.base_url,
            api_key_ref=settings.model_routing.retrieval_reranker.api_key or None,
        ),
    }
