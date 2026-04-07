import asyncio
from typing import Optional, TYPE_CHECKING
from domain.task import Task, TaskStatus, TaskResult
from interfaces.agents import SubAgent

if TYPE_CHECKING:
    from interfaces.storage import TaskStoreInterface, EventBusInterface


class Blackboard:
    """
    黑板：无状态服务对象，协调 Sub-agent 执行，广播完成事件。
    所有任务状态统一走 task_store，Blackboard 本身不持有任务数据。
    """

    def __init__(
        self,
        task_store: "TaskStoreInterface",
        event_bus: "EventBusInterface",
        agent_registry: Optional[dict[str, SubAgent]] = None,
    ):
        self.task_store = task_store
        self.event_bus = event_bus
        self.agent_registry: dict[str, SubAgent] = agent_registry or {}

    def register_agent(self, agent: "SubAgent") -> None:
        self.agent_registry[agent.name] = agent

    async def evaluate_agents(self, task: Task) -> tuple[Optional["SubAgent"], float]:
        """
        遍历 agent_registry，取最高能力评分的 agent。
        必须轻量（无网络调用，<10ms）。
        """
        best_agent: Optional["SubAgent"] = None
        best_score = 0.0

        for agent in self.agent_registry.values():
            score = await agent.estimate_capability(task)
            if score > best_score:
                best_agent, best_score = agent, score

        return best_agent, best_score

    async def assign(self, task: Task, agent: Optional["SubAgent"] = None) -> None:
        """
        将 Task 委派给指定 Sub-agent，不阻塞等待结果。
        若未指定 agent，自动评估选择最优。
        """
        if agent is None:
            agent, cap_score = await self.evaluate_agents(task)
            if agent is None:
                print("[Blackboard] 没有可用的 Agent")
                return

        task.assigned_to = agent.name
        task.status = TaskStatus.RUNNING
        task.last_heartbeat_at = task.last_heartbeat_at
        await self.task_store.update(task)

        asyncio.create_task(agent.execute(task))

    async def resume(self, task_id: str, hitl_result: dict) -> None:
        """
        HITL 用户响应后恢复挂起的任务。
        """
        task = await self.task_store.get(task_id)
        if not task:
            print(f"[Blackboard] 恢复任务失败：任务 {task_id} 不存在")
            return

        task.metadata["hitl_result"] = hitl_result
        await self.task_store.update(task)

        agent = self.agent_registry.get(task.assigned_to)
        if agent:
            asyncio.create_task(agent.resume(task, hitl_result))

    async def on_task_complete(self, task: Task) -> None:
        """
        任务完成：更新状态 + 广播 task_completed 事件（P1）。
        """
        task.status = TaskStatus.DONE
        await self.task_store.update(task)
        await self.event_bus.emit(
            "task_completed",
            {"task_id": task.id, "task": task.model_dump()},
        )

    async def on_task_failed(self, task: Task, error: str) -> None:
        """
        任务失败：记录 error_trace + 广播 task_failed 事件（P0，立即触发元认知反思）。
        """
        task.status = TaskStatus.FAILED
        task.error_trace = error
        await self.task_store.update(task)
        await self.event_bus.emit(
            "task_failed",
            {
                "task_id": task.id,
                "task": task.model_dump(),
                "error": error,
                "priority": 0,
            },
        )

    async def terminate_agent(self, agent_name: str) -> None:
        """
        TaskDAG 级联取消时调用，释放 agent 占用的资源。
        """
        agent = self.agent_registry.get(agent_name)
        if agent:
            await agent.cancel()
            print(f"[Blackboard] 已终止 Agent: {agent_name}")


class SubAgentDummy:
    """SubAgent 占位实现"""

    name = "dummy_agent"
    domain = "general"

    async def execute(self, task: Task) -> "TaskResult":
        from domain.task import TaskResult

        return TaskResult(task_id=task.id, status="done")

    async def estimate_capability(self, task: Task) -> float:
        return 0.5

    async def cancel(self) -> None:
        pass
