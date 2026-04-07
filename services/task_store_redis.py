from typing import Optional

import redis.asyncio as redis

from domain.task import Task
from interfaces.storage import TaskStoreInterface


class RedisTaskStore(TaskStoreInterface):
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    async def create(self, task: Task) -> Task:
        key = f"task:{task.id}"
        await self._redis.set(key, task.model_dump_json())
        await self._index_by_status(task.id, task.status)
        if task.parent_task_id:
            await self._index_by_parent(task.id, task.parent_task_id)
        return task

    async def get(self, task_id: str) -> Optional[Task]:
        key = f"task:{task_id}"
        data = await self._redis.get(key)
        if not data:
            print(f"[RedisTaskStore] Task {task_id} not found")
            return None
        return Task.model_validate_json(data)

    async def update(self, task: Task) -> None:
        key = f"task:{task.id}"
        await self._redis.set(key, task.model_dump_json())

    async def update_heartbeat(self, task_id: str, timestamp: any) -> None:
        key = f"task:{task_id}"
        await self._redis.hset(key, "heartbeat", str(timestamp))

    async def get_by_status(self, status: str) -> list[Task]:
        index_key = f"tasks:status:{status}"
        task_ids = await self._redis.smembers(index_key)
        if not task_ids:
            return []
        tasks = []
        for task_id in task_ids:
            task_id_str = task_id.decode() if isinstance(task_id, bytes) else task_id
            task = await self.get(task_id_str)
            if task:
                tasks.append(task)
        return tasks

    async def get_by_parent(self, parent_task_id: str) -> list[Task]:
        index_key = f"tasks:parent:{parent_task_id}"
        task_ids = await self._redis.smembers(index_key)
        if not task_ids:
            return []
        tasks = []
        for task_id in task_ids:
            task_id_str = task_id.decode() if isinstance(task_id, bytes) else task_id
            task = await self.get(task_id_str)
            if task:
                tasks.append(task)
        return tasks

    async def _index_by_status(self, task_id: str, status: str) -> None:
        index_key = f"tasks:status:{status}"
        await self._redis.sadd(index_key, task_id)

    async def _index_by_parent(self, task_id: str, parent_task_id: str) -> None:
        index_key = f"tasks:parent:{parent_task_id}"
        await self._redis.sadd(index_key, task_id)
