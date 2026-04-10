"""Redis Streams task workers for sub-agent execution."""

from __future__ import annotations

import asyncio
from typing import Any

from app.platform.base import OutboundMessage, PlatformContext


class TaskWorker:
    """Consume agent-specific Redis Streams and execute assigned tasks."""

    def __init__(
        self,
        *,
        agent: Any,
        task_store: Any,
        task_system: Any,
        blackboard: Any,
        platform_adapter: Any | None = None,
        poll_block_ms: int = 5000,
        pending_idle_ms: int = 30_000,
    ) -> None:
        self.agent = agent
        self.task_store = task_store
        self.task_system = task_system
        self.blackboard = blackboard
        self.platform_adapter = platform_adapter
        self.poll_block_ms = poll_block_ms
        self.pending_idle_ms = pending_idle_ms
        self.redis_client = task_system.redis_client
        self.streams = {
            task_system.stream_for_agent(agent.name, task_system.DISPATCH_STREAM): ">",
            task_system.stream_for_agent(agent.name, task_system.RETRY_STREAM): ">",
        }
        self.group = task_system.group_for_agent(agent.name)
        self.consumer = f"{agent.name}-worker"
        self._task: asyncio.Task[None] | None = None
        self.degraded = self.redis_client is None

    def start(self) -> None:
        if self.degraded:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        await self.task_system.ensure_worker_groups(self.agent.name)
        while True:
            await self._recover_pending()
            entries = await self.redis_client.xreadgroup(
                groupname=self.group,
                consumername=self.consumer,
                streams=self.streams,
                count=10,
                block=self.poll_block_ms,
            )
            for stream_name, messages in entries:
                for message_id, fields in messages:
                    await self._handle_message(stream_name, message_id, fields)

    async def _recover_pending(self) -> None:
        for stream_name in self.streams:
            try:
                _, claimed, _ = await self.redis_client.xautoclaim(
                    name=stream_name,
                    groupname=self.group,
                    consumername=self.consumer,
                    min_idle_time=self.pending_idle_ms,
                    start_id="0-0",
                    count=10,
                )
            except Exception:
                continue
            for message_id, fields in claimed:
                await self._handle_message(stream_name, message_id, fields)

    async def _handle_message(self, stream_name: str, message_id: str, fields: dict[str, Any]) -> None:
        task_id = self._decode(fields.get("task_id"))
        if not task_id:
            await self.redis_client.xack(stream_name, self.group, message_id)
            return
        task = await self.task_store.get(task_id)
        if task is None:
            await self.redis_client.xack(stream_name, self.group, message_id)
            return

        task.delivery_token = str(message_id)
        task.consumer_group = self.group
        await self.task_store.update(task)

        try:
            result = await self.agent.execute(task)
            await self._finalize(task, result)
            await self.redis_client.xack(stream_name, self.group, message_id)
        except Exception as exc:
            await self._handle_failure(task, f"RETRYABLE: {exc}")
            await self.redis_client.xack(stream_name, self.group, message_id)

    async def _finalize(self, task: Any, result: Any) -> None:
        if result.status == "done":
            await self.blackboard.on_task_complete(task, result.output or {})
            await self._notify_session(task, result.output or {})
            return
        if result.status in {"failed", "interrupted", "cancelled"}:
            await self._handle_failure(task, result.error or "task failed", result.metadata.get("error_type"))

    async def _handle_failure(self, task: Any, error: str, error_type: str | None = None) -> None:
        normalized = (error_type or "RETRYABLE").upper()
        if normalized == "RETRYABLE" and task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = "pending"
            await self.task_store.update(task)
            await self.task_system.publish_retry(task)
            return

        await self.blackboard.on_task_failed(task, error)
        await self.task_system.publish_dlq(task, error)
        await self._notify_failure(task, error)

    async def _notify_session(self, task: Any, output: dict[str, Any]) -> None:
        if self.platform_adapter is None:
            return
        session_id = task.metadata.get("session_id")
        user_id = task.metadata.get("user_id") or session_id
        if not session_id:
            return
        ctx = PlatformContext(platform="web", user_id=user_id, session_id=session_id)
        await self.platform_adapter.send_outbound(
            ctx,
            OutboundMessage(type="text", content=output.get("summary") or "任务已完成。", metadata=output),
        )

    async def _notify_failure(self, task: Any, error: str) -> None:
        if self.platform_adapter is None:
            return
        session_id = task.metadata.get("session_id")
        user_id = task.metadata.get("user_id") or session_id
        if not session_id:
            return
        ctx = PlatformContext(platform="web", user_id=user_id, session_id=session_id)
        await self.platform_adapter.send_outbound(
            ctx,
            OutboundMessage(type="text", content=f"任务执行失败：{error}"),
        )

    @staticmethod
    def _decode(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode()
        return str(value)


class TaskWorkerManager:
    """Own and lifecycle-manage all registered task workers."""

    def __init__(self, workers: list[TaskWorker]) -> None:
        self.workers = workers

    def start(self) -> None:
        for worker in self.workers:
            worker.start()

    async def stop(self) -> None:
        for worker in self.workers:
            await worker.stop()
