import json
from typing import TYPE_CHECKING, Any

from domain.evolution import VectorEntry

if TYPE_CHECKING:
    from services.graph_db import GraphDBClient
    from services.vector_db import VectorDBClient
    from services.llm import LLMInterface


class VectorDBInterfaceDummy:
    async def insert(self, entry: VectorEntry) -> None:
        print(f"[VectorDB] insert: namespace={entry.namespace}")

    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        return []


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
        graph_db: "GraphDBClient",
        vector_db: "VectorDBClient",
        llm_lite: "LLMInterface",
        event_bus: Any = None,
    ):
        self._graph_db = graph_db
        self._vector_db = vector_db
        self._llm = llm_lite
        self._event_bus = event_bus
        self._batch: list[dict] = []

    async def process(self, dialogue: list[dict], session_id: str) -> None:
        if not await self._is_salient(dialogue):
            print("[Observer] 对话不够显著，跳过")
            return

        knowledge_triplets = await self._extract_knowledge(dialogue)
        if not knowledge_triplets:
            print("[Observer] 未抽取到知识三元组")
            if self._event_bus:
                await self._event_bus.emit(
                    "observation_done",
                    {"session_id": session_id, "triplet_count": 0},
                    priority=1,
                )
            return

        for triplet in knowledge_triplets:
            await self._write_to_graph(triplet)
            await self._write_to_vector(triplet, session_id)

        if self._event_bus:
            await self._event_bus.emit(
                "observation_done",
                {"session_id": session_id, "triplet_count": len(knowledge_triplets)},
                priority=1,
            )

    async def _is_salient(self, dialogue: list[dict]) -> bool:
        return len(dialogue) > 3

    async def _extract_knowledge(self, dialogue: list[dict]) -> list[dict]:
        dialogue_text = "\n".join(
            f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
            for msg in dialogue
        )

        prompt = KNOWLEDGE_EXTRACTION_PROMPT.format(dialogue=dialogue_text)
        response = await self._llm.generate(prompt)

        if not response:
            print("[Observer] LLM returned empty response")
            return []

        try:
            parsed = json.loads(response)
            if isinstance(parsed, list):
                return parsed
            print(f"[Observer] LLM returned non-list JSON: {type(parsed)}")
            return []
        except json.JSONDecodeError as e:
            print(f"[Observer] Failed to parse LLM JSON response: {e}")
            return []

    async def _write_to_graph(self, triplet: dict) -> None:
        subject = triplet.get("subject")
        relation = triplet.get("relation")
        object = triplet.get("object")
        confidence = triplet.get("confidence", 0.5)
        is_pinned = triplet.get("is_pinned", False)

        if not all([subject, relation, object]):
            print(f"[Observer] Incomplete triplet, skipping graph write: {triplet}")
            return

        try:
            await self._graph_db.upsert_relation(
                subject=subject,
                relation=relation,
                object=object,
                confidence=confidence,
                is_pinned=is_pinned,
            )
            print(
                f"[Observer] Graph写入: {subject} - {relation} - {object} "
                f"(conf={confidence}, pinned={is_pinned})"
            )
        except Exception as e:
            print(f"[Observer] Graph写入失败: {e}")

    async def _write_to_vector(self, triplet: dict, session_id: str) -> None:
        content = f"{triplet.get('subject', '')} {triplet.get('relation', '')} {triplet.get('object', '')}"
        entry = VectorEntry(
            content=content,
            namespace="experience",
            metadata={
                "session_id": session_id,
                "relation": triplet.get("relation"),
                "confidence": triplet.get("confidence", 0.5),
            },
        )
        try:
            await self._vector_db.insert(entry)
            print(f"[Observer] Vector写入: {content[:50]}...")
        except Exception as e:
            print(f"[Observer] Vector写入失败: {e}")
