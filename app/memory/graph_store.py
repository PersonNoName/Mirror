"""Neo4j-backed graph memory storage."""

from __future__ import annotations

import json
from typing import Any

from neo4j import AsyncGraphDatabase

from app.config import settings


ALLOWED_RELATIONS = frozenset(
    {
        "PREFERS",
        "DISLIKES",
        "USES",
        "KNOWS",
        "HAS_CONSTRAINT",
        "IS_GOOD_AT",
        "IS_WEAK_AT",
    }
)


class GraphStore:
    """Store and query durable user graph relationships in Neo4j."""

    def __init__(
        self,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
    ) -> None:
        self.uri = uri or settings.neo4j.uri
        self.user = user or settings.neo4j.user
        self.password = password or settings.neo4j.password
        self.database = database or settings.neo4j.database
        self._driver = AsyncGraphDatabase.driver(self.uri, auth=(self.user, self.password))

    @staticmethod
    def _validate_relation(relation: str) -> str:
        if relation not in ALLOWED_RELATIONS:
            raise ValueError(f"unsupported relation type: {relation}")
        return relation

    async def upsert_relation(
        self,
        user_id: str,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        relation = self._validate_relation(relation)
        query = f"""
        MERGE (s:MemoryEntity {{user_id: $user_id, name: $subject}})
        MERGE (o:MemoryEntity {{user_id: $user_id, name: $object}})
        MERGE (s)-[r:{relation} {{user_id: $user_id}}]->(o)
        SET r.confidence = $confidence,
            r.metadata_json = $metadata_json,
            r.updated_at = datetime()
        """
        async with self._driver.session(database=self.database) as session:
            await session.run(
                query,
                user_id=user_id,
                subject=subject,
                object=object,
                confidence=confidence,
                metadata_json=json.dumps(metadata or {}),
            )

    async def get_relation(
        self,
        user_id: str,
        subject: str,
        relation: str,
        object: str,
    ) -> dict[str, Any] | None:
        relation = self._validate_relation(relation)
        query = f"""
        MATCH (s:MemoryEntity {{user_id: $user_id, name: $subject}})
              -[r:{relation} {{user_id: $user_id}}]->
              (o:MemoryEntity {{user_id: $user_id, name: $object}})
        RETURN s.name AS subject,
               type(r) AS relation,
               o.name AS object,
               r.confidence AS confidence,
               r.metadata_json AS metadata_json
        LIMIT 1
        """
        async with self._driver.session(database=self.database) as session:
            result = await session.run(
                query,
                user_id=user_id,
                subject=subject,
                object=object,
            )
            record = await result.single()
        if record is None:
            return None
        payload = dict(record)
        payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
        return payload

    async def query_relations_by_user(
        self,
        user_id: str,
        relation_types: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if relation_types:
            invalid = [item for item in relation_types if item not in ALLOWED_RELATIONS]
            if invalid:
                raise ValueError(f"unsupported relation types: {invalid}")
        query = """
        MATCH (s:MemoryEntity {user_id: $user_id})-[r]->(o:MemoryEntity {user_id: $user_id})
        WHERE $relation_types IS NULL OR type(r) IN $relation_types
        RETURN s.name AS subject,
               type(r) AS relation,
               o.name AS object,
               r.confidence AS confidence,
               r.metadata_json AS metadata_json
        ORDER BY r.updated_at DESC
        LIMIT $limit
        """
        async with self._driver.session(database=self.database) as session:
            result = await session.run(
                query,
                user_id=user_id,
                relation_types=relation_types,
                limit=limit,
            )
            records = await result.data()
        parsed: list[dict[str, Any]] = []
        for record in records:
            payload = dict(record)
            payload["metadata"] = json.loads(payload.pop("metadata_json") or "{}")
            parsed.append(payload)
        return parsed

    async def build_world_model_summary(self, user_id: str) -> str:
        relations = await self.query_relations_by_user(user_id=user_id, limit=10)
        if not relations:
            return "No world model facts recorded yet."
        lines = [
            f"{item['subject']} {item['relation']} {item['object']} "
            f"(confidence={item.get('confidence', 0.0):.2f})"
            for item in relations
        ]
        return "; ".join(lines)
