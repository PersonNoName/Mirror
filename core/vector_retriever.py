from typing import Optional
from domain.memory import CoreMemory


class VectorRetriever:
    """
    Vector DB 检索接口。
    实际检索逻辑在阶段三实现，当前为占位实现。
    """

    async def search(
        self,
        query: str,
        user_id: str,
        top_k: int = 8,
    ) -> str:
        return ""

    async def get_recent_dialogue(
        self,
        session_id: str,
        last_n: int = 5,
    ) -> str:
        return ""
