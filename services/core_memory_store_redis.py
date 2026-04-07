import json

import redis.asyncio as redis

from domain.memory import CoreMemory
from interfaces.storage import CoreMemoryStoreInterface


_CORE_MEMORY_BLOCKS = [
    "self_cognition",
    "world_model",
    "personality",
    "task_experience",
]

_CAS_LUA = """
local current = redis.call('HGET', KEYS[1], 'version')
if current and tonumber(current) ~= tonumber(ARGV[1]) then
    return 0
end
redis.call('HSET', KEYS[1], 'data', ARGV[2])
redis.call('HINCRBY', KEYS[1], 'version', 1)
return 1
"""


class RedisCoreMemoryStore(CoreMemoryStoreInterface):
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    async def get_with_version(self, key: str) -> tuple[dict, int]:
        full_key = f"cm:{key}"
        data = await self._redis.hget(full_key, "data")
        version_str = await self._redis.hget(full_key, "version")
        parsed_data = json.loads(data) if data else {}
        version = int(version_str) if version_str else 0
        return parsed_data, version

    async def cas_upsert(self, key: str, value: dict, expected_version: int) -> bool:
        full_key = f"cm:{key}"
        result = await self._redis.eval(
            _CAS_LUA,
            1,
            full_key,
            str(expected_version),
            json.dumps(value),
        )
        return bool(result)

    async def force_upsert(self, key: str, value: dict) -> None:
        full_key = f"cm:{key}"
        pipe = self._redis.pipeline()
        pipe.hset(full_key, "data", json.dumps(value))
        pipe.hincrby(full_key, "version", 1)
        await pipe.execute()

    async def get_core_memory(self, user_id: str) -> CoreMemory:
        blocks: dict[str, dict] = {}
        for block_name in _CORE_MEMORY_BLOCKS:
            block_key = f"{user_id}:{block_name}"
            data, _ = await self.get_with_version(block_key)
            if data:
                from domain.memory import (
                    SelfCognition,
                    WorldModel,
                    PersonalityState,
                    TaskExperience,
                )

                block_map = {
                    "self_cognition": SelfCognition,
                    "world_model": WorldModel,
                    "personality": PersonalityState,
                    "task_experience": TaskExperience,
                }
                model_cls = block_map.get(block_name)
                if model_cls:
                    blocks[block_name] = model_cls.model_validate(data)
                else:
                    blocks[block_name] = data
            else:
                from domain.memory import (
                    SelfCognition,
                    WorldModel,
                    PersonalityState,
                    TaskExperience,
                )

                defaults = {
                    "self_cognition": SelfCognition,
                    "world_model": WorldModel,
                    "personality": PersonalityState,
                    "task_experience": TaskExperience,
                }
                blocks[block_name] = defaults[block_name]()

        return CoreMemory(
            self_cognition=blocks.get("self_cognition", SelfCognition()),
            world_model=blocks.get("world_model", WorldModel()),
            personality=blocks.get("personality", PersonalityState()),
            task_experience=blocks.get("task_experience", TaskExperience()),
        )
