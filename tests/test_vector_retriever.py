from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.memory import CoreMemory
from app.memory.vector_retriever import VectorRetriever


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        self.calls.append(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeRerankerModel:
    def __init__(self, result: list[dict[str, Any]] | None = None) -> None:
        self.result = result or []
        self.calls: list[dict[str, Any]] = []

    async def rerank(self, query: str, docs: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append({"query": query, "docs": docs})
        return list(self.result)


class FakeModelRegistry:
    def __init__(self, rerank_result: list[dict[str, Any]] | None = None) -> None:
        self.embedding_model = FakeEmbeddingModel()
        self.reranker_model = FakeRerankerModel(rerank_result)

    def embedding(self, profile: str) -> FakeEmbeddingModel:
        assert profile == "retrieval.embedding"
        return self.embedding_model

    def reranker(self, profile: str) -> FakeRerankerModel:
        assert profile == "retrieval.reranker"
        return self.reranker_model


class FakeCoreMemoryCache:
    def __init__(self, core_memory: CoreMemory | None = None) -> None:
        self.core_memory = core_memory or CoreMemory()
        self.calls: list[str] = []

    async def get(self, user_id: str) -> CoreMemory:
        self.calls.append(user_id)
        return self.core_memory


class FakeQdrantClient:
    def __init__(self, *, collection_exists: bool = True, points: list[Any] | None = None) -> None:
        self.collection_exists_value = collection_exists
        self.points = points or []
        self.collection_exists_calls = 0
        self.query_calls: list[dict[str, Any]] = []

    async def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls += 1
        return self.collection_exists_value

    async def query_points(
        self,
        *,
        collection_name: str,
        query: list[float],
        query_filter: Any,
        limit: int,
    ) -> Any:
        self.query_calls.append(
            {
                "collection_name": collection_name,
                "query": query,
                "query_filter": query_filter,
                "limit": limit,
            }
        )
        return SimpleNamespace(points=list(self.points))


def scored_point(
    point_id: str,
    score: float,
    content: str,
    namespace: str,
    metadata: dict[str, Any] | None = None,
) -> Any:
    return SimpleNamespace(
        id=point_id,
        score=score,
        payload={
            "content": content,
            "namespace": namespace,
            "metadata": metadata or {},
            "is_pinned": False,
        },
    )


@pytest.mark.asyncio
async def test_vector_retriever_returns_empty_matches_when_collection_missing() -> None:
    registry = FakeModelRegistry()
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(collection_exists=False),
    )

    result = await retriever.retrieve(user_id="user-1", query="hello")

    assert result["matches"] == []
    assert isinstance(result["core_memory"], CoreMemory)
    assert registry.embedding_model.calls == []
    assert registry.reranker_model.calls == []


@pytest.mark.asyncio
async def test_vector_retriever_applies_namespace_filter() -> None:
    registry = FakeModelRegistry()
    client = FakeQdrantClient(
        points=[scored_point("p1", 0.9, "doc one", "experience")],
    )
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=client,
    )

    result = await retriever.retrieve(
        user_id="user-1",
        query="find prior experience",
        namespaces=["experience", "world_model"],
        limit=5,
    )

    assert len(result["matches"]) == 1
    query_filter = client.query_calls[0]["query_filter"]
    namespace_condition = next(condition for condition in query_filter.must if condition.key == "namespace")
    assert namespace_condition.match.any == ["experience", "world_model"]


@pytest.mark.asyncio
async def test_vector_retriever_returns_empty_matches_when_query_has_no_results() -> None:
    registry = FakeModelRegistry()
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(collection_exists=True, points=[]),
    )

    result = await retriever.retrieve(user_id="user-1", query="nothing")

    assert result["matches"] == []
    assert len(registry.embedding_model.calls) == 1
    assert registry.reranker_model.calls == []


@pytest.mark.asyncio
async def test_vector_retriever_skips_rerank_for_low_variance_scores() -> None:
    registry = FakeModelRegistry()
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(
            points=[
                scored_point("p1", 0.81, "doc one", "experience"),
                scored_point("p2", 0.80, "doc two", "world_model"),
            ]
        ),
        rerank_variance_threshold=0.15,
    )

    result = await retriever.retrieve(user_id="user-1", query="stable scores")

    assert [item["id"] for item in result["matches"]] == ["p1", "p2"]
    assert registry.reranker_model.calls == []


@pytest.mark.asyncio
async def test_vector_retriever_calls_reranker_for_high_variance_scores() -> None:
    registry = FakeModelRegistry(
        rerank_result=[
            {"index": 1, "score": 0.98},
            {"index": 0, "score": 0.50},
        ]
    )
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(
            points=[
                scored_point("p1", 0.95, "doc one", "experience"),
                scored_point("p2", 0.10, "doc two", "world_model"),
            ]
        ),
        rerank_variance_threshold=0.01,
    )

    result = await retriever.retrieve(user_id="user-1", query="rerank me")

    assert [item["id"] for item in result["matches"]] == ["p2", "p1"]
    assert result["matches"][0]["rerank_score"] == 0.98
    assert len(registry.reranker_model.calls) == 1


@pytest.mark.asyncio
async def test_vector_retriever_preserves_unmatched_recalled_items_when_rerank_is_partial() -> None:
    registry = FakeModelRegistry(rerank_result=[{"index": 1, "score": 0.99}])
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(
            points=[
                scored_point("p1", 0.92, "doc one", "experience"),
                scored_point("p2", 0.11, "doc two", "world_model"),
                scored_point("p3", 0.10, "doc three", "dialogue_fragment"),
            ]
        ),
        rerank_variance_threshold=0.01,
    )

    result = await retriever.retrieve(user_id="user-1", query="partial rerank")

    assert [item["id"] for item in result["matches"]] == ["p2", "p1", "p3"]
    assert "rerank_score" in result["matches"][0]
    assert "rerank_score" not in result["matches"][1]


@pytest.mark.asyncio
async def test_vector_retriever_falls_back_cleanly_for_malformed_rerank_indices() -> None:
    registry = FakeModelRegistry(
        rerank_result=[
            {"index": 99, "score": 1.0},
            {"document_index": -1, "relevance_score": 0.5},
        ]
    )
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(
            points=[
                scored_point("p1", 0.93, "doc one", "experience"),
                scored_point("p2", 0.12, "doc two", "world_model"),
            ]
        ),
        rerank_variance_threshold=0.01,
    )

    result = await retriever.retrieve(user_id="user-1", query="bad rerank")

    assert [item["id"] for item in result["matches"]] == ["p1", "p2"]


@pytest.mark.asyncio
async def test_vector_retriever_respects_limit_and_final_top_k() -> None:
    registry = FakeModelRegistry()
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=FakeQdrantClient(
            points=[
                scored_point("p1", 0.93, "doc one", "experience"),
                scored_point("p2", 0.92, "doc two", "world_model"),
                scored_point("p3", 0.91, "doc three", "dialogue_fragment"),
            ]
        ),
        final_top_k=2,
    )

    result = await retriever.retrieve(user_id="user-1", query="cap result", limit=5)

    assert [item["id"] for item in result["matches"]] == ["p1", "p2"]
