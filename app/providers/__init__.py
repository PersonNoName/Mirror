"""Model provider package."""

from app.providers.base import ChatModel, EmbeddingModel, ModelSpec, RerankerModel
from app.providers.openai_compat import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    OpenAICompatibleRerankerModel,
    ProviderRequestError,
)
from app.providers.registry import ModelProviderRegistry, build_routing_from_settings

__all__ = [
    "ChatModel",
    "EmbeddingModel",
    "ModelProviderRegistry",
    "ModelSpec",
    "OpenAICompatibleChatModel",
    "OpenAICompatibleEmbeddingModel",
    "OpenAICompatibleRerankerModel",
    "ProviderRequestError",
    "RerankerModel",
    "build_routing_from_settings",
]
