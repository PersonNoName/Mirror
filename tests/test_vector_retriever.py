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
    def __init__(
        self,
        *,
        collection_exists: bool = True,
        points: list[Any] | None = None,
        collection_exists_error: Exception | None = None,
        scroll_error: Exception | None = None,
    ) -> None:
        self.collection_exists_value = collection_exists
        self.points = points or []
        self.collection_exists_error = collection_exists_error
        self.scroll_error = scroll_error
        self.collection_exists_calls = 0
        self.query_calls: list[dict[str, Any]] = []
        self.scroll_calls: list[dict[str, Any]] = []
        self.close_calls = 0

    async def collection_exists(self, collection_name: str) -> bool:
        self.collection_exists_calls += 1
        if self.collection_exists_error is not None:
            raise self.collection_exists_error
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

    async def scroll(
        self,
        *,
        collection_name: str,
        scroll_filter: Any,
        limit: int,
        with_payload: bool,
        with_vectors: bool,
    ) -> Any:
        if self.scroll_error is not None:
            raise self.scroll_error
        self.scroll_calls.append(
            {
                "collection_name": collection_name,
                "scroll_filter": scroll_filter,
                "limit": limit,
                "with_payload": with_payload,
                "with_vectors": with_vectors,
            }
        )
        return (list(self.points), None)

    async def aclose(self) -> None:
        self.close_calls += 1


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


def record_point(
    point_id: str,
    content: str,
    namespace: str,
    metadata: dict[str, Any] | None = None,
    created_at: str = "2026-04-12T00:00:00+00:00",
) -> Any:
    return SimpleNamespace(
        id=point_id,
        payload={
            "content": content,
            "namespace": namespace,
            "metadata": metadata or {},
            "is_pinned": False,
            "truth_type": "fact",
            "status": "active",
            "confirmed_by_user": False,
            "created_at": created_at,
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
async def test_vector_retriever_accepts_conversation_episode_namespace() -> None:
    registry = FakeModelRegistry()
    client = FakeQdrantClient(
        points=[scored_point("p1", 0.9, "prior conversation", "conversation_episode")],
    )
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=client,
    )

    result = await retriever.retrieve(
        user_id="user-1",
        query="what did we talk about before",
        namespaces=["conversation_episode"],
    )

    assert result["matches"][0]["namespace"] == "conversation_episode"


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


@pytest.mark.asyncio
async def test_vector_retriever_lists_conversation_episode_namespace_items() -> None:
    registry = FakeModelRegistry()
    client = FakeQdrantClient(
        points=[
            record_point("e1", "Older episode", "conversation_episode", created_at="2026-04-10T00:00:00+00:00"),
            record_point("e2", "Newer episode", "conversation_episode", created_at="2026-04-12T00:00:00+00:00"),
        ],
    )
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=client,
    )

    items = await retriever.list_namespace_items(
        user_id="user-1",
        namespace="conversation_episode",
        limit=10,
    )

    assert [item["id"] for item in items] == ["e2", "e1"]
    namespace_condition = next(condition for condition in client.scroll_calls[0]["scroll_filter"].must if condition.key == "namespace")
    assert namespace_condition.match.any == ["conversation_episode"]


@pytest.mark.asyncio
async def test_vector_retriever_lists_namespace_items_returns_empty_when_qdrant_fails() -> None:
    registry = FakeModelRegistry()
    client = FakeQdrantClient(
        collection_exists_error=RuntimeError("qdrant bad gateway"),
    )
    failing_recreated_client = FakeQdrantClient(
        collection_exists_error=RuntimeError("qdrant still bad gateway"),
    )
    original_factory = VectorRetriever.__init__.__globals__["AsyncQdrantClient"]
    VectorRetriever.__init__.__globals__["AsyncQdrantClient"] = lambda **kwargs: failing_recreated_client
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=client,
    )
    try:
        items = await retriever.list_namespace_items(
            user_id="user-1",
            namespace="conversation_episode",
            limit=10,
        )
    finally:
        VectorRetriever.__init__.__globals__["AsyncQdrantClient"] = original_factory

    assert items == []
    assert retriever.last_namespace_list_error(
        user_id="user-1", namespace="conversation_episode"
    ) == "qdrant_bad_gateway"


@pytest.mark.asyncio
async def test_vector_retriever_recreates_client_and_retries_namespace_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = FakeModelRegistry()
    first_client = FakeQdrantClient(scroll_error=RuntimeError("stale client"))
    second_client = FakeQdrantClient(
        points=[record_point("e2", "Recovered episode", "conversation_episode")],
    )
    created_clients: list[FakeQdrantClient] = []

    def fake_async_qdrant_client(**kwargs: Any) -> FakeQdrantClient:
        created_clients.append(second_client)
        return second_client

    monkeypatch.setattr("app.memory.vector_retriever.AsyncQdrantClient", fake_async_qdrant_client)
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=first_client,
    )

    items = await retriever.list_namespace_items(
        user_id="user-1",
        namespace="conversation_episode",
        limit=10,
    )

    assert [item["id"] for item in items] == ["e2"]
    assert first_client.close_calls == 1
    assert created_clients == [second_client]


@pytest.mark.asyncio
async def test_vector_retriever_ping_reports_bad_gateway() -> None:
    registry = FakeModelRegistry()
    client = FakeQdrantClient(collection_exists_error=RuntimeError("502 Bad Gateway"))
    failing_recreated_client = FakeQdrantClient(collection_exists_error=RuntimeError("502 Bad Gateway"))
    original_factory = VectorRetriever.__init__.__globals__["AsyncQdrantClient"]
    VectorRetriever.__init__.__globals__["AsyncQdrantClient"] = lambda **kwargs: failing_recreated_client
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
        qdrant_client=client,
    )
    try:
        ok, reason = await retriever.ping()
    finally:
        VectorRetriever.__init__.__globals__["AsyncQdrantClient"] = original_factory

    assert ok is False
    assert reason == "qdrant_bad_gateway"


def test_vector_retriever_disables_env_proxy_for_qdrant_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = FakeModelRegistry()
    created_kwargs: list[dict[str, Any]] = []

    class StubClient:
        async def collection_exists(self, collection_name: str) -> bool:
            return True

        async def aclose(self) -> None:
            return None

    def fake_async_qdrant_client(**kwargs: Any) -> StubClient:
        created_kwargs.append(kwargs)
        return StubClient()

    monkeypatch.setattr("app.memory.vector_retriever.AsyncQdrantClient", fake_async_qdrant_client)
    retriever = VectorRetriever(
        model_registry=registry,
        core_memory_cache=FakeCoreMemoryCache(),
    )

    assert created_kwargs[0]["trust_env"] is False

    import asyncio

    asyncio.run(retriever._recreate_client())
    assert created_kwargs[1]["trust_env"] is False
