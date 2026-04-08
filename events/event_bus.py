import asyncio
from typing import Callable, Awaitable
from dataclasses import dataclass
from domain.evolution import Event


EVENT_BUS_CONFIG = {
    "max_queue_depth": 1000,
    "drop_policy": "drop_lowest_priority",
    "alert_threshold": 800,
}


@dataclass
class QueuedEvent:
    priority: int
    event: Event


class EventBus:
    """
    异步事件总线：基于 asyncio.Queue 实现，支持背压保护。
    事件类型：
    - dialogue_ended → 触发 Observer + SignalExtractor
    - task_completed → 触发元认知反思（P1）
    - task_failed → 触发元认知反思（P0，立即）
    - hitl_feedback → 触发人格信号
    - lesson_generated → 触发认知进化器
    - evolution_done → 触发 Core Memory 写入调度器
    """

    def __init__(self, config: dict = None):
        self.config = config or EVENT_BUS_CONFIG
        self.max_queue_depth = self.config["max_queue_depth"]
        self.alert_threshold = self.config["alert_threshold"]
        self._queue: asyncio.Queue[QueuedEvent] = asyncio.Queue(
            maxsize=self.max_queue_depth
        )
        self._handlers: dict[str, list[Callable[[Event], Awaitable[None]]]] = {}
        self._running = False
        self._processor_task: asyncio.Task | None = None

    async def emit(self, event_type: str, payload: dict, priority: int = 1) -> None:
        """
        发布事件。priority: 0=最高优先（如task_failed），1=普通
        """
        event = Event(type=event_type, payload=payload)
        queued = QueuedEvent(priority=priority, event=event)

        try:
            self._queue.put_nowait(queued)
        except asyncio.QueueFull:
            if self.config["drop_policy"] == "drop_lowest_priority" and priority > 0:
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(queued)
                    print("[EventBus] 背压丢弃最低优先事件")
                except asyncio.QueueEmpty:
                    pass
            else:
                print("[EventBus] 事件队列已满，事件丢失")

        if self._queue.qsize() > self.alert_threshold:
            print(f"[EventBus] 警告：队列深度 {self._queue.qsize()} 超过告警阈值")

    async def subscribe(
        self, event_type: str, handler: Callable[[Event], Awaitable[None]]
    ) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def unsubscribe(
        self, event_type: str, handler: Callable[[Event], Awaitable[None]]
    ) -> None:
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]

    async def start(self) -> None:
        self._running = True
        self._processor_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

    async def _process_loop(self) -> None:
        while self._running:
            try:
                queued = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch(queued.event)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def _dispatch(self, event: Event) -> None:
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                print(f"[EventBus] 处理器异常 {event.type}: {e}")
