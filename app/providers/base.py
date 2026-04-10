"""Provider-facing model contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(slots=True)
class ModelSpec:
    """Configuration contract for a routed model profile."""

    profile: str
    capability: Literal["chat", "embedding", "rerank"]
    provider_type: Literal["openai_compatible", "ollama", "native", "anthropic"]
    vendor: str
    model: str
    base_url: str
    api_key_ref: str | None = None
    timeout_seconds: int = 60
    max_retries: int = 2
    metadata: dict[str, Any] = field(default_factory=dict)


class ChatModel(ABC):
    """Text or multimodal generation contract."""

    @abstractmethod
    async def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        """Generate a non-streaming response."""

    async def stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Optionally stream response chunks."""

        raise NotImplementedError


class EmbeddingModel(ABC):
    """Vector embedding contract."""

    @abstractmethod
    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        """Embed a batch of texts into vectors."""


class RerankerModel(ABC):
    """Document reranking contract."""

    @abstractmethod
    async def rerank(
        self,
        query: str,
        docs: list[str],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Return reranked documents with scores and metadata."""

