import asyncio
from datetime import datetime, timedelta
from typing import Optional, Any, Callable, Awaitable
from dataclasses import dataclass
import json


@dataclass
class DedupEntry:
    event_id: str
    created_at: datetime
    expires_at: datetime


class IdempotentWriter:
    """
    幂等写入器：确保同一事件不会被重复处理。

    使用内存 + 可选外部存储（Redis）实现去重表。
    支持 TTL 自动清理，防止内存泄漏。
    """

    DEFAULT_TTL_HOURS = 24

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        ttl_hours: int = DEFAULT_TTL_HOURS,
    ):
        self._redis = redis_client
        self._ttl_hours = ttl_hours
        self._memory_dedup: dict[str, DedupEntry] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def write(
        self,
        event_id: str,
        data: dict,
        target: str,
        write_func: Callable[[dict], Awaitable[None]],
    ) -> bool:
        """
        幂等写入。

        Returns:
            True if written, False if duplicate (skipped)
        """
        if await self._is_duplicate(event_id):
            print(f"[IdempotentWriter] 跳过重复事件: {event_id}")
            return False

        await write_func(data)

        await self._mark_processed(event_id)
        return True

    async def is_processed(self, event_id: str) -> bool:
        """检查事件是否已处理"""
        return await self._is_duplicate(event_id)

    async def _is_duplicate(self, event_id: str) -> bool:
        if self._redis:
            key = f"dedup:{event_id}"
            exists = await self._redis.exists(key)
            return bool(exists)

        if event_id in self._memory_dedup:
            entry = self._memory_dedup[event_id]
            if datetime.utcnow() < entry.expires_at:
                return True
            else:
                del self._memory_dedup[event_id]
        return False

    async def _mark_processed(self, event_id: str) -> None:
        now = datetime.utcnow()
        expires_at = now + timedelta(hours=self._ttl_hours)
        entry = DedupEntry(
            event_id=event_id,
            created_at=now,
            expires_at=expires_at,
        )

        if self._redis:
            key = f"dedup:{event_id}"
            value = json.dumps(
                {
                    "created_at": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                }
            )
            await self._redis.setex(key, self._ttl_hours * 3600, value)
        else:
            self._memory_dedup[event_id] = entry

    async def _cleanup_loop(self) -> None:
        while self._running:
            await asyncio.sleep(3600)
            await self._cleanup_expired()

    async def _cleanup_expired(self) -> None:
        now = datetime.utcnow()

        if self._redis:
            pass
        else:
            expired_keys = [
                eid
                for eid, entry in self._memory_dedup.items()
                if now >= entry.expires_at
            ]
            for key in expired_keys:
                del self._memory_dedup[key]

            if expired_keys:
                print(f"[IdempotentWriter] 清理了 {len(expired_keys)} 个过期去重记录")


class IdempotentEventHandler:
    """
    装饰器包装器：为事件处理器添加幂等性保证。
    """

    def __init__(self, writer: IdempotentWriter):
        self._writer = writer

    def wrap(self, handler: Callable) -> Callable:
        async def wrapped(event: Any) -> None:
            event_id = self._extract_event_id(event)
            if not event_id:
                await handler(event)
                return

            async def do_write(data: dict) -> None:
                await handler(event)

            await self._writer.write(
                event_id=event_id,
                data={"event": event},
                target="handler",
                write_func=do_write,
            )

        return wrapped

    def _extract_event_id(self, event: Any) -> Optional[str]:
        if hasattr(event, "payload") and isinstance(event.payload, dict):
            return event.payload.get("event_id")
        if isinstance(event, dict):
            return event.get("event_id")
        return None
