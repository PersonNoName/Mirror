"""Qdrant-backed vector retrieval with optional reranking."""

from __future__ import annotations

import hashlib
import statistics
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import structlog
from qdrant_client import AsyncQdrantClient, models

from app.config import settings
from app.memory.core_memory import CoreMemoryCache
from app.providers.registry import ModelProviderRegistry


VECTOR_COLLECTION = "mirror_memory"
VECTOR_NAMESPACES = frozenset(
    {"experience", "self_cognition", "world_model", "dialogue_fragment", "conversation_episode", "mid_term_memory"}
)
logger = structlog.get_logger(__name__)


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
            check_compatibility=False,
            trust_env=False,
        )
        self.collection_name = collection_name
        self.recall_top_k = recall_top_k
        self.final_top_k = final_top_k
        self.rerank_variance_threshold = rerank_variance_threshold
        self._last_namespace_list_error: dict[tuple[str, str], str] = {}
        self.last_qdrant_error: str | None = None

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
        vector = (
            await self.model_registry.embedding("retrieval.embedding").embed([content])
        )[0]
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
        await self._call_qdrant(
            "upsert",
            self.qdrant_client.upsert,
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
        query_filter = self._build_filter(
            user_id=user_id, namespaces=requested_namespaces
        )
        results = await self._call_qdrant(
            "query_points",
            self.qdrant_client.query_points,
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
        if (
            len(scores) > 1
            and statistics.pvariance(scores) > self.rerank_variance_threshold
        ):
            reranked = await self.model_registry.reranker("retrieval.reranker").rerank(
                query=query,
                docs=[item["content"] for item in matches],
            )
            matches = self._merge_reranked(matches, reranked)

        return {"core_memory": core_memory, "matches": matches[:final_limit]}

    async def list_namespace_items(
        self,
        *,
        user_id: str,
        namespace: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        self._last_namespace_list_error.pop((user_id, namespace), None)
        self._validate_namespace(namespace)
        try:
            return await self._list_namespace_items_once(
                user_id=user_id,
                namespace=namespace,
                limit=limit,
            )
        except Exception:
            self._last_namespace_list_error[(user_id, namespace)] = self.last_qdrant_error or "qdrant_request_failed"
            logger.exception(
                "vector_namespace_list_failed",
                user_id=user_id,
                namespace=namespace,
                collection_name=self.collection_name,
                attempt=1,
            )
        await self._recreate_client()
        try:
            return await self._list_namespace_items_once(
                user_id=user_id,
                namespace=namespace,
                limit=limit,
            )
        except Exception:
            self._last_namespace_list_error[(user_id, namespace)] = self.last_qdrant_error or "qdrant_request_failed"
            logger.exception(
                "vector_namespace_list_failed",
                user_id=user_id,
                namespace=namespace,
                collection_name=self.collection_name,
                attempt=2,
            )
            return []

    def last_namespace_list_error(self, *, user_id: str, namespace: str) -> str | None:
        return self._last_namespace_list_error.get((user_id, namespace))

    async def _list_namespace_items_once(
        self,
        *,
        user_id: str,
        namespace: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not await self._collection_exists():
            return []
        scroll_filter = self._build_filter(user_id=user_id, namespaces=[namespace])
        result = await self._call_qdrant(
            "scroll",
            self.qdrant_client.scroll,
            collection_name=self.collection_name,
            scroll_filter=scroll_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        points = result[0] if isinstance(result, tuple) else getattr(result, "points", [])
        items = [self._record_to_dict(point) for point in points]
        items.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return items[:limit]

    async def _recreate_client(self) -> None:
        close = getattr(self.qdrant_client, "close", None)
        if callable(close):
            maybe_result = close()
            if hasattr(maybe_result, "__await__"):
                await maybe_result
        aclose = getattr(self.qdrant_client, "aclose", None)
        if callable(aclose):
            await aclose()
        self.qdrant_client = AsyncQdrantClient(
            url=settings.qdrant.url,
            api_key=settings.qdrant.api_key or None,
            check_compatibility=False,
            trust_env=False,
        )

    async def _ensure_collection(self, vector_size: int) -> None:
        if await self._collection_exists():
            return
        await self._call_qdrant(
            "create_collection",
            self.qdrant_client.create_collection,
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=models.Distance.COSINE,
            ),
        )

    async def _collection_exists(self) -> bool:
        return await self._call_qdrant(
            "collection_exists",
            self.qdrant_client.collection_exists,
            self.collection_name,
        )

    async def ping(self) -> tuple[bool, str | None]:
        try:
            await self._collection_exists()
            self.last_qdrant_error = None
            return True, None
        except Exception:
            error = self.last_qdrant_error or "qdrant_request_failed"
            return False, error

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
    def _record_to_dict(point: Any) -> dict[str, Any]:
        payload = point.payload or {}
        metadata = dict(payload.get("metadata", {}))
        return {
            "id": str(point.id),
            "content": payload.get("content", ""),
            "namespace": payload.get("namespace", ""),
            "metadata": metadata,
            "is_pinned": bool(payload.get("is_pinned", False)),
            "truth_type": payload.get("truth_type", "fact"),
            "status": payload.get("status", "active"),
            "confirmed_by_user": bool(payload.get("confirmed_by_user", False)),
            "created_at": payload.get("created_at", metadata.get("created_at", "")),
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
            item
            for _, item in sorted(
                enriched,
                key=lambda pair: pair[1].get("rerank_score", 0.0),
                reverse=True,
            )
        ]
        remaining = [
            dict(match) for idx, match in enumerate(matches) if idx not in seen_indices
        ]
        return reranked_items + remaining

    async def _call_qdrant(self, operation: str, func: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            result = await func(*args, **kwargs)
            self.last_qdrant_error = None
            return result
        except Exception as exc:
            self.last_qdrant_error = self._classify_qdrant_error(exc)
            logger.exception(
                "qdrant_operation_failed",
                operation=operation,
                collection_name=self.collection_name,
                attempt=1,
            )
        await self._recreate_client()
        rebound = getattr(self.qdrant_client, getattr(func, "__name__", operation))
        try:
            result = await rebound(*args, **kwargs)
            self.last_qdrant_error = None
            return result
        except Exception as exc:
            self.last_qdrant_error = self._classify_qdrant_error(exc)
            logger.exception(
                "qdrant_operation_failed",
                operation=operation,
                collection_name=self.collection_name,
                attempt=2,
            )
            raise

    @staticmethod
    def _classify_qdrant_error(exc: Exception) -> str:
        message = str(exc).lower()
        if "502" in message or "bad gateway" in message:
            return "qdrant_bad_gateway"
        if "timeout" in message:
            return "qdrant_timeout"
        return "qdrant_request_failed"
