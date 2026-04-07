from typing import Optional
from domain.evolution import VectorEntry


class VectorDBInterfaceDummy:
    """VectorDB 占位实现"""

    async def insert(self, entry: VectorEntry) -> None:
        print(f"[VectorDB] insert: namespace={entry.namespace}")

    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        return []


class LLMInterfaceDummy:
    """LLM 调用占位实现"""

    async def generate(self, prompt: str) -> list[dict]:
        print(f"[LLM] 知识抽取调用（占位）")
        return [
            {
                "subject": "用户",
                "relation": "PREFERS",
                "object": "Python",
                "confidence": 0.9,
            }
        ]


KNOWLEDGE_EXTRACTION_PROMPT = """
从以下对话中抽取结构化知识三元组。

约束：
- 只抽取有置信度的事实，不推断
- Subject 必须是明确的实体（用户、工具、环境）
- Relation 使用预定义词表：PREFERS / DISLIKES / USES / KNOWS / HAS_CONSTRAINT / IS_GOOD_AT / IS_WEAK_AT
- 若无可抽取内容，返回空数组

输出格式（JSON 数组）：
[
  {{"subject": "用户", "relation": "PREFERS", "object": "Python", "confidence": 0.9}}
]

对话内容：
{dialogue}
"""


class ObserverEngine:
    """
    Observer 后台观察引擎：从对话中异步抽取知识三元组。
    订阅 dialogue_ended 事件，写入 Graph DB 与 Vector DB。
    """

    BATCH_WINDOW_SECONDS = 30
    MAX_BATCH_SIZE = 5

    def __init__(
        self,
        graph_db: Optional[VectorDBInterfaceDummy] = None,
        vector_db: Optional[VectorDBInterfaceDummy] = None,
        llm_lite: Optional[LLMInterfaceDummy] = None,
    ):
        self.graph_db = graph_db or VectorDBInterfaceDummy()
        self.vector_db = vector_db or VectorDBInterfaceDummy()
        self.llm_lite = llm_lite or LLMInterfaceDummy()
        self._batch: list[dict] = []

    async def process(self, dialogue: list[dict], session_id: str) -> None:
        """
        处理对话，提取知识三元组并写入存储。
        """
        if not await self._is_salient(dialogue):
            print("[Observer] 对话不够显著，跳过")
            return

        knowledge_triplets = await self._extract_knowledge(dialogue)
        for triplet in knowledge_triplets:
            await self._write_to_graph(triplet)
            await self._write_to_vector(triplet, session_id)

    async def _is_salient(self, dialogue: list[dict]) -> bool:
        """
        判断对话是否足够显著，值得提取知识。
        简化实现：超过3轮对话即认为显著。
        """
        return len(dialogue) > 3

    async def _extract_knowledge(self, dialogue: list[dict]) -> list[dict]:
        """
        调用 LLM 抽取知识三元组。
        """
        dialogue_text = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in dialogue
        )

        prompt = KNOWLEDGE_EXTRACTION_PROMPT.format(dialogue=dialogue_text)
        result = await self.llm_lite.generate(prompt)

        if isinstance(result, str):
            import json

            try:
                result = json.loads(result)
            except json.JSONDecodeError:
                return []

        return result if isinstance(result, list) else []

    async def _write_to_graph(self, triplet: dict) -> None:
        """
        写入 Graph DB。
        """
        print(
            f"[Observer] Graph写入: {triplet.get('subject')} - "
            f"{triplet.get('relation')} - {triplet.get('object')} "
            f"(conf={triplet.get('confidence', 0.5)})"
        )

    async def _write_to_vector(self, triplet: dict, session_id: str) -> None:
        """
        写入 Vector DB。
        """
        content = f"{triplet.get('subject')} {triplet.get('relation')} {triplet.get('object')}"
        entry = VectorEntry(
            content=content,
            namespace="experience",
            metadata={
                "session_id": session_id,
                "relation": triplet.get("relation"),
                "confidence": triplet.get("confidence", 0.5),
            },
        )
        await self.vector_db.insert(entry)
