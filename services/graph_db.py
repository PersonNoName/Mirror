from typing import Optional, TYPE_CHECKING

import neo4j

from interfaces.storage import GraphDBInterface

if TYPE_CHECKING:
    from neo4j import AsyncDriver


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


class Neo4jGraphDB(GraphDBInterface):
    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
    ):
        self._driver: "AsyncDriver" = neo4j.AsyncGraphDatabase.driver(
            uri, auth=(user, password)
        )
        self._database = database

    async def close(self) -> None:
        await self._driver.close()

    async def upsert_relation(
        self,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        is_pinned: bool = False,
    ) -> None:
        cypher = f"""
        MERGE (s:Entity {{name: $subject}})
        MERGE (o:Entity {{name: $object}})
        MERGE (s)-[r:{relation} {{}}]->(o)
        SET r.confidence = $confidence,
            r.is_pinned = $is_pinned,
            r.updated_at = datetime()
        RETURN r
        """
        async with self._driver.session(database=self._database) as session:
            await session.run(
                cypher,
                subject=subject,
                object=object,
                confidence=confidence,
                is_pinned=is_pinned,
            )

    async def get_relation(self, subject: str, object: str) -> Optional[dict]:
        cypher = """
        MATCH (s:Entity {name: $subject})-[r]->(o:Entity {name: $object})
        RETURN type(r) as relation, r.confidence as confidence, r.is_pinned as is_pinned
        LIMIT 1
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, subject=subject, object=object)
            record = await result.single()
            if not record:
                return None
            return {
                "subject": subject,
                "relation": record["relation"],
                "object": object,
                "confidence": record["confidence"],
                "is_pinned": record["is_pinned"],
            }

    async def query_user_preferences(self, user_id: str) -> dict:
        cypher = """
        MATCH (s:Entity {name: $user_id})-[r]->(o)
        WHERE type(r) IN ['PREFERS', 'DISLIKES', 'USES', 'HAS_CONSTRAINT']
        RETURN type(r) as relation, o.name as object, r.confidence as confidence, r.is_pinned as is_pinned
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, user_id=user_id)
            records = await result.values()
            preferences = {}
            for row in records:
                rel, obj, conf, pinned = row
                if rel not in preferences:
                    preferences[rel] = []
                preferences[rel].append(
                    {"object": obj, "confidence": conf, "is_pinned": pinned}
                )
            return preferences

    async def query_agent_capabilities(self) -> dict:
        cypher = """
        MATCH (a:Agent)-[r:IS_GOOD_AT|IS_WEAK_AT]->(d:Domain)
        RETURN a.name as agent, type(r) as relation, d.name as domain, r.confidence as confidence
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher)
            records = await result.values()
            capabilities = {}
            for row in records:
                agent, rel, domain, conf = row
                if agent not in capabilities:
                    capabilities[agent] = []
                capabilities[agent].append(
                    {"domain": domain, "relation": rel, "confidence": conf}
                )
            return capabilities

    async def query_env_constraints(self) -> list[str]:
        cypher = """
        MATCH (e:Environment)-[r:HAS_CONSTRAINT]->(c:Constraint)
        RETURN c.name as constraint
        """
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher)
            records = await result.values()
            return [row[0] for row in records if row[0]]

    async def decay_confidence(
        self,
        relation_type: str,
        half_life_days: int,
    ) -> None:
        cypher = f"""
        MATCH ()-[r:{relation_type}]->()
        WHERE r.is_pinned = false
        SET r.confidence = r.confidence * exp(-log(2) / $half_life_days * 1.0)
        """
        async with self._driver.session(database=self._database) as session:
            await session.run(cypher, half_life_days=half_life_days)


class GraphDBClient:
    def __init__(self, db_impl: Optional[GraphDBInterface] = None):
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
        return current_confidence


class GraphDBClientDummy:
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
