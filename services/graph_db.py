from typing import Optional
from domain.evolution import VectorEntry


GRAPH_DB_CONFIG = {
    "write_strategy": "upsert_with_timestamp",
    "confidence_decay": {
        "enabled": True,
        "exclude_pinned": True,
        "half_life_by_relation": {
            "PREFERS": 180,
            "DISLIKES": 180,
            "KNOWS": 180,
            "IS_GOOD_AT": 120,
            "IS_WEAK_AT": 120,
            "USES": 60,
            "HAS_CONSTRAINT": 30,
        },
        "default_half_life_days": 90,
    },
}


class GraphDBClient:
    """
    Graph DB 基础设施防腐层 (ACL)。
    实现命名空间路由、置信度衰减、is_pinned 免疫机制。
    """

    def __init__(self, db_impl: Optional["GraphDBInterface"] = None):
        from interfaces.storage import GraphDBInterface

        self._impl: GraphDBInterface = db_impl or GraphDBClientDummy()
        self._config = GRAPH_DB_CONFIG

    async def upsert_relation(
        self,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        is_pinned: bool = False,
    ) -> None:
        """
        写入关系，考虑 pinned 免疫和时间衰减。
        """
        if self._config["confidence_decay"]["enabled"] and not is_pinned:
            adjusted_confidence = self._apply_time_decay(relation, confidence)
        else:
            adjusted_confidence = confidence

        await self._impl.upsert_relation(
            subject=subject,
            relation=relation,
            object=object,
            confidence=adjusted_confidence,
            is_pinned=is_pinned,
        )

    async def get_relation(self, subject: str, object: str) -> Optional[dict]:
        return await self._impl.get_relation(subject, object)

    async def query_user_preferences(self, user_id: str) -> dict:
        return await self._impl.query_user_preferences(user_id)

    async def query_agent_capabilities(self) -> dict:
        return await self._impl.query_agent_capabilities()

    async def query_env_constraints(self) -> list[str]:
        return await self._impl.query_env_constraints()

    async def decay_confidence(
        self,
        relation_type: Optional[str] = None,
        half_life_days: Optional[int] = None,
    ) -> None:
        """
        执行置信度衰减。
        """
        if relation_type:
            await self._impl.decay_confidence(
                relation_type=relation_type,
                half_life_days=half_life_days
                or self._config["confidence_decay"]["half_life_by_relation"].get(
                    relation_type,
                    self._config["confidence_decay"]["default_half_life_days"],
                ),
            )
        else:
            for rel, hl in self._config["confidence_decay"][
                "half_life_by_relation"
            ].items():
                await self._impl.decay_confidence(relation_type=rel, half_life_days=hl)

    def _apply_time_decay(self, relation_type: str, current_confidence: float) -> float:
        """
        应用时间衰减（简化实现，返回原置信度）。
        实际应根据关系类型的半衰期计算。
        """
        half_life_days = self._config["confidence_decay"]["half_life_by_relation"].get(
            relation_type,
            self._config["confidence_decay"]["default_half_life_days"],
        )
        return current_confidence


class GraphDBClientDummy:
    """GraphDB 占位实现"""

    async def upsert_relation(
        self,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        is_pinned: bool = False,
    ) -> None:
        print(
            f"[GraphDB] upsert: {subject} - {relation} - {object} "
            f"(conf={confidence}, pinned={is_pinned})"
        )

    async def get_relation(self, subject: str, object: str) -> Optional[dict]:
        return None

    async def query_user_preferences(self, user_id: str) -> dict:
        return {}

    async def query_agent_capabilities(self) -> dict:
        return {}

    async def query_env_constraints(self) -> list[str]:
        return []

    async def decay_confidence(
        self,
        relation_type: str,
        half_life_days: int,
    ) -> None:
        print(f"[GraphDB] decay: {relation_type}, half_life={half_life_days}")
