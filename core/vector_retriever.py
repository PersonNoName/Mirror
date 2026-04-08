from typing import TYPE_CHECKING, Optional, Protocol
import os

import redis.asyncio as redis
import aiohttp
from openai import AsyncOpenAI

if TYPE_CHECKING:
    from services.vector_db import VectorDBClient


class EmbedderInterface(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-ada-002",
        base_url: str | None = None,
    ):
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding


class OllamaEmbedder:
    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "nomic-embed-text"
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def embed(self, text: str) -> list[float]:
        async with aiohttp.ClientSession() as session:
            response = await session.post(
                f"{self._base_url}/api/embed",
                json={"model": self._model, "input": [text]},
            )
            response.raise_for_status()
            data = await response.json()
            return data.get("embeddings", [[]])[0]


class EmbedderDummy:
    async def embed(self, text: str) -> list[float]:
        import random

        return [random.random() for _ in range(1536)]


def create_embedder() -> EmbedderInterface:
    EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "").strip().lower()

    if EMBEDDING_PROVIDER == "ollama":
        ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        ollama_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").strip()
        print(f"[EmbedderFactory] Using Ollama: {ollama_url}, model={ollama_model}")
        return OllamaEmbedder(base_url=ollama_url, model=ollama_model)

    if EMBEDDING_PROVIDER in ("openai", "miniMax", "minimax"):
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        openai_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small").strip()
        base_url = os.getenv("LLM_BASE_URL", "").strip() or None
        print(
            f"[EmbedderFactory] Using OpenAI-compatible: base_url={base_url}, model={openai_model}"
        )
        return OpenAIEmbedder(api_key=openai_key, model=openai_model, base_url=base_url)

    print("[EmbedderFactory] No valid EMBEDDING_PROVIDER set, using Dummy")
    return EmbedderDummy()


class VectorRetriever:
    def __init__(
        self,
        embedder: EmbedderInterface,
        vector_db: "VectorDBClient",
        redis_client: Optional[redis.Redis] = None,
    ):
        self._embedder = embedder
        self._vector_db = vector_db
        self._redis = redis_client

    async def search(self, query: str, user_id: str, top_k: int = 8) -> str:
        try:
            query_vec = await self._embedder.embed(query)
        except Exception as e:
            print(f"[VectorRetriever] Embedding failed: {e}, returning empty context")
            return ""
        namespace = f"user:{user_id}"
        results = await self._vector_db.search(
            query_embedding=query_vec,
            namespace=namespace,
            top_k=top_k,
        )
        return "\n".join([r.content for r in results])

    async def get_recent_dialogue(self, session_id: str, last_n: int = 5) -> str:
        if not self._redis:
            print(
                "[VectorRetriever] No Redis client configured, returning empty dialogue"
            )
            return ""

        key = f"dialogue:{session_id}"
        raw = await self._redis.lrange(key, -last_n, -1)
        if not raw:
            return ""

        lines = []
        for item in raw:
            text = item.decode() if isinstance(item, bytes) else item
            lines.append(text)
        return "\n".join(lines)

    async def append_dialogue(self, session_id: str, role: str, content: str) -> None:
        if not self._redis:
            print(
                "[VectorRetriever] No Redis client configured, cannot append dialogue"
            )
            return

        key = f"dialogue:{session_id}"
        await self._redis.rpush(key, f"{role}: {content}")
