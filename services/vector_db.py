from typing import Optional
from domain.evolution import VectorEntry


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


class VectorDBClient:
    """
    Vector DB 基础设施防腐层 (ACL)。
    实现命名空间路由和 is_pinned 免疫的淘汰策略。
    """

    def __init__(self, db_impl: Optional["VectorDBInterface"] = None):
        from interfaces.storage import VectorDBInterface

        self._impl: VectorDBInterface = db_impl or VectorDBClientDummy()
        self._config = VECTOR_DB_CONFIG

    async def insert(
        self,
        entry: VectorEntry,
        namespace: Optional[str] = None,
    ) -> None:
        """
        插入向量条目，自动路由到指定命名空间。
        """
        ns = namespace or entry.namespace
        await self._enforce_namespace_limit(ns)
        await self._impl.insert(entry)

    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        """
        搜索向量，限制在指定命名空间。
        """
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
        """
        更新 pinned 状态（pinned 条目免疫淘汰）。
        """
        await self._impl.update_pinned_status(entry_id, namespace, is_pinned)

    async def get_by_namespace(
        self,
        namespace: str,
        limit: int = 100,
    ) -> list[VectorEntry]:
        """
        获取指定命名空间的所有条目（占位）。
        """
        return []

    async def _enforce_namespace_limit(self, namespace: str) -> None:
        """
        执行命名空间容量限制，淘汰最不重要的非 pinned 条目。
        """
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
        """
        获取命名空间条目数量（占位）。
        """
        return 0

    async def _select_eviction_candidates(
        self, namespace: str, count: int
    ) -> list[VectorEntry]:
        """
        选择要淘汰的条目（排除 pinned）。
        按 least_important 策略选择（简化实现：随机选）。
        """
        all_entries = await self.get_by_namespace(namespace, limit=1000)
        unpinned = [e for e in all_entries if not e.is_pinned]
        return unpinned[:count]


class VectorDBClientDummy:
    """VectorDB 占位实现"""

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
