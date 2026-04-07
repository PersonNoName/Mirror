import asyncio
from typing import Optional, TYPE_CHECKING, Any
from datetime import datetime
from domain.task import Task, TaskStatus

if TYPE_CHECKING:
    from interfaces.storage import TaskStoreInterface


class TaskDAG:
    """
    任务依赖 DAG：管理任务间的依赖关系，支持级联取消。
    """

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._dependents: dict[str, list[str]] = {}
        self._waiters: dict[str, list[Task]] = {}

    def add_task(self, task: Task) -> None:
        self._tasks[task.id] = task
        for dep_id in task.depends_on:
            if dep_id not in self._dependents:
                self._dependents[dep_id] = []
            self._dependents[dep_id].append(task.id)

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def all_deps_done(self, task: Task) -> bool:
        for dep_id in task.depends_on:
            dep_task = self._tasks.get(dep_id)
            if dep_task is None or dep_task.status != TaskStatus.DONE:
                return False
        return True

    def unblock(self, completed_task_id: str) -> list[Task]:
        unblocked = []
        if completed_task_id in self._dependents:
            for dependent_id in self._dependents[completed_task_id]:
                dependent = self._tasks.get(dependent_id)
                if dependent and dependent.status == TaskStatus.PENDING:
                    if self.all_deps_done(dependent):
                        unblocked.append(dependent)
        return unblocked

    def get_children(self, task_id: str) -> list[str]:
        return self._dependents.get(task_id, [])


class TaskQueue:
    """
    三级优先级队列 + 依赖 DAG 调度。
    优先级：0=紧急, 1=正常, 2=低优
    """

    def __init__(self, dag: TaskDAG):
        self.dag = dag
        self.queues: dict[int, asyncio.PriorityQueue] = {
            0: asyncio.PriorityQueue(),
            1: asyncio.PriorityQueue(),
            2: asyncio.PriorityQueue(),
        }

    async def enqueue(self, task: Task) -> None:
        if self.dag.all_deps_done(task):
            await self.queues[task.priority].put((task.priority, task.id, task))
        else:
            if task.id not in self.dag._waiters:
                self.dag._waiters[task.id] = []
            self.dag._waiters[task.id].append(task)

    async def dequeue(self) -> Optional[Task]:
        for priority in [0, 1, 2]:
            q = self.queues[priority]
            if not q.empty():
                _, _, task = await q.get()
                return task
        return None

    async def on_task_done(self, task_id: str) -> list[Task]:
        unblocked = self.dag.unblock(task_id)
        for t in unblocked:
            await self.enqueue(t)
        return unblocked

    def get_pending_count(self) -> int:
        return sum(q.qsize() for q in self.queues.values())


class TaskMonitor:
    """
    心跳检活监控：防止 Sub-agent 崩溃导致任务永久卡在 running 状态。
    """

    def __init__(
        self,
        task_store: "TaskStoreInterface",
        blackboard: Any,
        check_interval: int = 10,
    ):
        self.task_store = task_store
        self.blackboard = blackboard
        self.check_interval = check_interval
        self._running = False
        self._sweeper_task: Optional[asyncio.Task] = None

    async def start_sweeper(self) -> None:
        self._running = True
        self._sweeper_task = asyncio.create_task(self._sweep_loop())

    async def stop_sweeper(self) -> None:
        self._running = False
        if self._sweeper_task:
            self._sweeper_task.cancel()
            try:
                await self._sweeper_task
            except asyncio.CancelledError:
                pass

    async def _sweep_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.check_interval)
            await self._check_stale_tasks()

    async def _check_stale_tasks(self) -> None:
        now = datetime.utcnow()
        running_tasks = await self.task_store.get_by_status(TaskStatus.RUNNING.value)
        for task in running_tasks:
            elapsed = (now - task.last_heartbeat_at).total_seconds()
            if elapsed > task.heartbeat_timeout:
                print(
                    f"[TaskMonitor] 任务 {task.id} 心跳丢失 "
                    f"(elapsed={elapsed:.1f}s, timeout={task.heartbeat_timeout}s)"
                )
                await self.blackboard.on_task_failed(task, "Agent Heartbeat Lost")


class TaskSystem:
    """
    任务系统：整合 TaskQueue、TaskDAG、TaskMonitor。
    """

    def __init__(
        self,
        task_store: "TaskStoreInterface",
        blackboard: Any,
    ):
        self.task_store = task_store
        self.blackboard = blackboard
        self.dag = TaskDAG()
        self.queue = TaskQueue(self.dag)
        self.monitor = TaskMonitor(
            task_store=task_store,
            blackboard=blackboard,
        )

    async def start(self) -> None:
        await self.monitor.start_sweeper()

    async def stop(self) -> None:
        await self.monitor.stop_sweeper()

    async def create_task(self, task_spec: dict) -> Task:
        task = Task(**task_spec)
        task = await self.task_store.create(task)
        self.dag.add_task(task)
        await self.queue.enqueue(task)
        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        return await self.task_store.get(task_id)

    async def on_task_done(self, task: Task) -> None:
        task.status = TaskStatus.DONE
        await self.task_store.update(task)
        await self.queue.on_task_done(task.id)
        await self.blackboard.on_task_complete(task)

    async def on_task_failed(
        self, task: Task, error_trace: str, is_retryable: bool = True
    ) -> None:
        task.error_trace = error_trace

        if is_retryable and task.retry_count < task.max_retries:
            task.retry_count += 1
            task.status = TaskStatus.PENDING
            await self.task_store.update(task)
            print(
                f"[TaskSystem] 任务 {task.id} 重试 ({task.retry_count}/{task.max_retries})"
            )
        else:
            task.status = TaskStatus.FAILED
            await self.task_store.update(task)
            await self.queue.on_task_done(task.id)
            await self.blackboard.on_task_failed(task, error_trace)

    async def cancel_task_cascade(self, task_id: str) -> None:
        task = self.dag.get_task(task_id)
        if not task:
            return

        task.status = TaskStatus.CANCELLED
        await self.task_store.update(task)

        for child_id in self.dag.get_children(task_id):
            child = self.dag.get_task(child_id)
            if child and child.status in [TaskStatus.PENDING, TaskStatus.RUNNING]:
                await self.cancel_task_cascade(child_id)
