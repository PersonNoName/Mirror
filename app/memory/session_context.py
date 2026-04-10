"""Redis-backed session context storage."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis


class SessionContextStore:
    """Store short-lived session messages and adaptations in Redis."""

    MAX_MESSAGES = 5
    MAX_ADAPTATIONS = 5

    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    @staticmethod
    def _messages_key(user_id: str, session_id: str) -> str:
        return f"session_ctx:{user_id}:{session_id}:messages"

    @staticmethod
    def _adaptations_key(user_id: str, session_id: str) -> str:
        return f"session_ctx:{user_id}:{session_id}:adaptations"

    async def append_message(self, user_id: str, session_id: str, message: dict[str, Any]) -> None:
        key = self._messages_key(user_id, session_id)
        await self.redis.rpush(key, json.dumps(message))
        await self.redis.ltrim(key, -self.MAX_MESSAGES, -1)

    async def get_recent_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        key = self._messages_key(user_id, session_id)
        raw_items = await self.redis.lrange(key, 0, -1)
        return [json.loads(item.decode() if isinstance(item, bytes) else item) for item in raw_items]

    async def set_adaptations(self, user_id: str, session_id: str, adaptations: list[str]) -> None:
        key = self._adaptations_key(user_id, session_id)
        values = [json.dumps(item) for item in adaptations[-self.MAX_ADAPTATIONS :]]
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete(key)
            if values:
                pipe.rpush(key, *values)
            await pipe.execute()

    async def get_adaptations(self, user_id: str, session_id: str) -> list[str]:
        key = self._adaptations_key(user_id, session_id)
        raw_items = await self.redis.lrange(key, 0, -1)
        return [json.loads(item.decode() if isinstance(item, bytes) else item) for item in raw_items]

    async def clear_session(self, user_id: str, session_id: str) -> None:
        await self.redis.delete(
            self._messages_key(user_id, session_id),
            self._adaptations_key(user_id, session_id),
        )
