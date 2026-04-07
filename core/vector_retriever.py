from typing import TYPE_CHECKING, Optional, Protocol

import redis.asyncio as redis

if TYPE_CHECKING:
    from services.vector_db import VectorDBClient


class EmbedderInterface(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(self, api_key: str, model: str = "text-embedding-ada-002"):
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def embed(self, text: str) -> list[float]:
        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
        )
        return response.data[0].embedding


class EmbedderDummy:
    async def embed(self, text: str) -> list[float]:
        import random

        return [random.random() for _ in range(1536)]


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
        query_vec = await self._embedder.embed(query)
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
