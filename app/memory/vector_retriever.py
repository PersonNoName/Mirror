"""Qdrant-backed vector retrieval with optional reranking."""

from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import AsyncQdrantClient, models

from app.config import settings
from app.memory.core_memory import CoreMemoryCache
from app.providers.registry import ModelProviderRegistry


VECTOR_COLLECTION = "mirror_memory"
VECTOR_NAMESPACES = frozenset(
    {"experience", "self_cognition", "world_model", "dialogue_fragment"}
)


class VectorRetriever:
    """Two-level retriever backed by Qdrant and model-based reranking."""

    def __init__(
        self,
        model_registry: ModelProviderRegistry,
        core_memory_cache: CoreMemoryCache,
        qdrant_client: AsyncQdrantClient | None = None,
        collection_name: str = VECTOR_COLLECTION,
        recall_top_k: int = 20,
        final_top_k: int = 8,
        rerank_variance_threshold: float = 0.15,
    ) -> None:
        self.model_registry = model_registry
        self.core_memory_cache = core_memory_cache
        self.qdrant_client = qdrant_client or AsyncQdrantClient(
            url=settings.qdrant.url,
            api_key=settings.qdrant.api_key or None,
        )
        self.collection_name = collection_name
        self.recall_top_k = recall_top_k
        self.final_top_k = final_top_k
        self.rerank_variance_threshold = rerank_variance_threshold

    async def upsert(
        self,
        user_id: str,
        namespace: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        is_pinned: bool = False,
        truth_type: str = "fact",
        status: str = "active",
        confirmed_by_user: bool = False,
    ) -> str:
        self._validate_namespace(namespace)
        vector = (await self.model_registry.embedding("retrieval.embedding").embed([content]))[0]
        await self._ensure_collection(len(vector))
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        point_id = str(uuid5(NAMESPACE_URL, f"{user_id}:{namespace}:{content_hash}"))
        payload = {
            "user_id": user_id,
            "namespace": namespace,
            "content": content,
            "content_hash": content_hash,
            "is_pinned": is_pinned,
            "truth_type": truth_type,
            "status": status,
            "confirmed_by_user": confirmed_by_user,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        point = models.PointStruct(id=point_id, vector=vector, payload=payload)
        await self.qdrant_client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )
        return point_id

    async def retrieve(
        self,
        user_id: str,
        query: str,
        namespaces: list[str] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        core_memory = await self.core_memory_cache.get(user_id)
        requested_namespaces = namespaces or list(VECTOR_NAMESPACES)
        for namespace in requested_namespaces:
            self._validate_namespace(namespace)

        if not await self._collection_exists():
            return {"core_memory": core_memory, "matches": []}

        query_vector = (
            await self.model_registry.embedding("retrieval.embedding").embed([query])
        )[0]
        query_filter = self._build_filter(user_id=user_id, namespaces=requested_namespaces)
        results = await self.qdrant_client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=self.recall_top_k,
        )
        matches = [self._scored_point_to_dict(item) for item in results.points]
        if not matches:
            return {"core_memory": core_memory, "matches": []}

        final_limit = min(limit, self.final_top_k)
        scores = [item["score"] for item in matches]
        if len(scores) > 1 and statistics.pvariance(scores) > self.rerank_variance_threshold:
            reranked = await self.model_registry.reranker("retrieval.reranker").rerank(
                query=query,
                docs=[item["content"] for item in matches],
            )
            matches = self._merge_reranked(matches, reranked)

        return {"core_memory": core_memory, "matches": matches[:final_limit]}

    async def _ensure_collection(self, vector_size: int) -> None:
        if await self._collection_exists():
            return
        await self.qdrant_client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    async def _collection_exists(self) -> bool:
        return await self.qdrant_client.collection_exists(self.collection_name)

    @staticmethod
    def _validate_namespace(namespace: str) -> None:
        if namespace not in VECTOR_NAMESPACES:
            raise ValueError(f"unsupported vector namespace: {namespace}")

    @staticmethod
    def _build_filter(user_id: str, namespaces: list[str]) -> models.Filter:
        conditions: list[models.FieldCondition] = [
            models.FieldCondition(
                key="user_id",
                match=models.MatchValue(value=user_id),
            )
        ]
        if namespaces:
            conditions.append(
                models.FieldCondition(
                    key="namespace",
                    match=models.MatchAny(any=namespaces),
                )
            )
        return models.Filter(must=conditions)

    @staticmethod
    def _scored_point_to_dict(point: models.ScoredPoint) -> dict[str, Any]:
        payload = point.payload or {}
        return {
            "id": str(point.id),
            "content": payload.get("content", ""),
            "score": float(point.score or 0.0),
            "namespace": payload.get("namespace", ""),
            "metadata": dict(payload.get("metadata", {})),
            "is_pinned": bool(payload.get("is_pinned", False)),
            "truth_type": payload.get("truth_type", "fact"),
            "status": payload.get("status", "active"),
            "confirmed_by_user": bool(payload.get("confirmed_by_user", False)),
        }

    @staticmethod
    def _merge_reranked(
        matches: list[dict[str, Any]],
        reranked: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        enriched: list[tuple[int, dict[str, Any]]] = []
        seen_indices: set[int] = set()
        for position, item in enumerate(reranked):
            index = item.get("index", item.get("document_index", position))
            if not isinstance(index, int) or index < 0 or index >= len(matches):
                continue
            if index in seen_indices:
                continue
            merged = dict(matches[index])
            merged["rerank_score"] = float(
                item.get("score", item.get("relevance_score", merged["score"]))
            )
            enriched.append((index, merged))
            seen_indices.add(index)
        if not enriched:
            return matches
        reranked_items = [
            item for _, item in sorted(enriched, key=lambda pair: pair[1].get("rerank_score", 0.0), reverse=True)
        ]
        remaining = [dict(match) for idx, match in enumerate(matches) if idx not in seen_indices]
        return reranked_items + remaining
