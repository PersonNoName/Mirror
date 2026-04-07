from typing import Optional

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from domain.evolution import VectorEntry
from interfaces.storage import VectorDBInterface


VECTOR_DB_CONFIG = {
    "batch_size": 20,
    "dedup_strategy": "content_hash",
    "async_embed": True,
    "max_entries_per_namespace": 10000,
    "eviction_policy": "least_important_unpinned",
}

VECTOR_NAMESPACES = {
    "experience": "任务经验与反思日志",
    "self_cognition": "自我认知快照",
    "world_experience": "情境性世界观经验",
    "dialogue_fragment": "重要对话片段",
}


class QdrantVectorDB(VectorDBInterface):
    def __init__(
        self,
        url: str,
        api_key: Optional[str] = None,
        collection_name: str = "mirror_vectors",
    ):
        self._client = AsyncQdrantClient(url=url, api_key=api_key)
        self._collection = collection_name

    async def insert(self, entry: VectorEntry) -> None:
        if entry.embedding is None:
            print(f"[QdrantVectorDB] Cannot insert entry {entry.id}: no embedding")
            return

        payload = entry.model_dump()
        payload.pop("embedding", None)

        await self._client.upsert(
            collection_name=self._collection,
            points=[
                {
                    "id": entry.id,
                    "vector": entry.embedding,
                    "payload": payload,
                }
            ],
        )

    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        results = await self._client.search(
            collection_name=self._collection,
            query_vector=query_embedding,
            limit=top_k,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="namespace",
                        match=models.MatchValue(value=namespace),
                    )
                ]
            ),
        )
        entries = []
        for result in results:
            payload = result.payload
            payload["embedding"] = result.vector
            try:
                entries.append(VectorEntry.model_validate(payload))
            except Exception as e:
                print(f"[QdrantVectorDB] Failed to deserialize entry: {e}")
        return entries

    async def delete(self, entry_id: str, namespace: str) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.PointIdsList(points=[entry_id]),
        )

    async def update_pinned_status(
        self,
        entry_id: str,
        namespace: str,
        is_pinned: bool,
    ) -> None:
        self._client.set_payload(
            collection_name=self._collection,
            payload={"is_pinned": is_pinned},
            points=[entry_id],
        )


class VectorDBClient:
    def __init__(self, db_impl: Optional["VectorDBInterface"] = None):
        from interfaces.storage import VectorDBInterface

        self._impl: VectorDBInterface = db_impl or VectorDBClientDummy()
        self._config = VECTOR_DB_CONFIG

    async def insert(
        self,
        entry: VectorEntry,
        namespace: Optional[str] = None,
    ) -> None:
        ns = namespace or entry.namespace
        await self._enforce_namespace_limit(ns)
        await self._impl.insert(entry)

    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        return await self._impl.search(
            query_embedding=query_embedding,
            namespace=namespace,
            top_k=top_k,
        )

    async def delete(self, entry_id: str, namespace: str) -> None:
        await self._impl.delete(entry_id, namespace)

    async def update_pinned_status(
        self,
        entry_id: str,
        namespace: str,
        is_pinned: bool,
    ) -> None:
        await self._impl.update_pinned_status(entry_id, namespace, is_pinned)

    async def get_by_namespace(
        self,
        namespace: str,
        limit: int = 100,
    ) -> list[VectorEntry]:
        return []

    async def _enforce_namespace_limit(self, namespace: str) -> None:
        current_count = await self._get_namespace_count(namespace)
        max_count = self._config["max_entries_per_namespace"]

        if current_count >= max_count:
            entries_to_evict = await self._select_eviction_candidates(
                namespace, count=current_count - max_count + 1
            )
            for entry in entries_to_evict:
                await self._impl.delete(entry.id, namespace)
                print(
                    f"[VectorDBClient] 淘汰条目: {entry.id} "
                    f"(namespace={namespace}, pinned={entry.is_pinned})"
                )

    async def _get_namespace_count(self, namespace: str) -> int:
        return 0

    async def _select_eviction_candidates(
        self, namespace: str, count: int
    ) -> list[VectorEntry]:
        all_entries = await self.get_by_namespace(namespace, limit=1000)
        unpinned = [e for e in all_entries if not e.is_pinned]
        return unpinned[:count]


class VectorDBClientDummy:
    async def insert(self, entry: VectorEntry) -> None:
        print(f"[VectorDB] insert: {entry.namespace} - {entry.content[:50]}...")

    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        return []

    async def delete(self, entry_id: str, namespace: str) -> None:
        print(f"[VectorDB] delete: {entry_id} from {namespace}")

    async def update_pinned_status(
        self,
        entry_id: str,
        namespace: str,
        is_pinned: bool,
    ) -> None:
        print(f"[VectorDB] update_pinned: {entry_id} -> {is_pinned}")
