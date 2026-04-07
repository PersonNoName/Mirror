from typing import Literal, Optional
from domain.task import Task, TaskResult


class TaskSystemDummy:
    """Task 系统占位实现"""

    async def create(self, task_spec: dict) -> Task:
        print(f"[TaskSystemDummy] 创建任务: {task_spec.get('intent', 'unknown')}")
        return Task(
            intent=task_spec.get("intent", ""),
            created_by="soul_engine",
            assigned_to=task_spec.get("assigned_to", ""),
        )

    async def get(self, task_id: str) -> Optional[Task]:
        return None


class BlackboardDummy:
    """Blackboard 占位实现"""

    async def evaluate_agents(self, task: Task) -> tuple[Optional[object], float]:
        print(f"[BlackboardDummy] 评估 agents for task: {task.id}")
        return None, 0.5

    async def assign(self, task: Task, agent: object) -> None:
        print(f"[BlackboardDummy] 分配任务 {task.id} 到 agent")

    async def on_task_complete(self, task: Task) -> None:
        print(f"[BlackboardDummy] 任务完成: {task.id}")

    async def on_task_failed(self, task: Task, error: str) -> None:
        print(f"[BlackboardDummy] 任务失败: {task.id}, error: {error}")

    async def resume(self, task_id: str, hitl_result: dict) -> None:
        print(f"[BlackboardDummy] 恢复任务: {task_id}")


class HITLGatewayDummy:
    """HITL 网关占位实现"""

    async def ask_user(self, message: str) -> dict:
        print(f"[HITLGatewayDummy] 请求用户确认: {message}")
        return {"approved": True, "result": "用户确认"}


class ToolExecutorDummy:
    """工具执行器占位实现"""

    async def run(self, tool_spec: dict) -> dict:
        print(f"[ToolExecutorDummy] 执行工具: {tool_spec}")
        return {"success": True, "result": "工具执行结果"}


class EventBusDummy:
    """事件总线占位实现"""

    async def emit(self, event_type: str, payload: dict) -> None:
        print(f"[EventBusDummy] 发送事件: {event_type}")


class ActionRouter:
    """
    动作路由区：根据 SoulEngine 输出的 action 类型，分发到不同处理器。
    """

    def __init__(
        self,
        task_system: TaskSystemDummy,
        blackboard: BlackboardDummy,
        hitl_gateway: HITLGatewayDummy,
        tool_executor: ToolExecutorDummy,
        event_bus: EventBusDummy,
    ):
        self.task_system = task_system
        self.blackboard = blackboard
        self.hitl_gateway = hitl_gateway
        self.tool_executor = tool_executor
        self.event_bus = event_bus

    async def route(self, action_output: dict) -> None:
        action_type = action_output.get("action")
        content = action_output.get("content", "")

        match action_type:
            case "direct_reply":
                await self._handle_direct_reply(content)

            case "publish_task":
                await self._handle_publish_task(content)

            case "tool_call":
                await self._handle_tool_call(content)

            case "hitl_relay":
                await self._handle_hitl_relay(content)

            case _:
                print(f"[ActionRouter] 未知动作类型: {action_type}")

    async def _handle_direct_reply(self, content: str) -> None:
        print(f"[ActionRouter] direct_reply: {content[:100]}...")
        await self.event_bus.emit("dialogue_ended", {"reply": content})

    async def _handle_publish_task(self, task_spec: dict) -> None:
        task = await self.task_system.create(task_spec)
        best_agent, cap_score = await self.blackboard.evaluate_agents(task)

        if cap_score < 0.3:
            fallback_msg = (
                f"当前工具无法稳妥完成此任务（置信度 {cap_score}），请求指示。"
            )
            result = await self.hitl_gateway.ask_user(fallback_msg)
            print(f"[ActionRouter] 低置信度 HITL: {fallback_msg}")
            await self.blackboard.resume(task.id, result)
        elif cap_score < 0.5:
            await self.blackboard.assign(task, best_agent)
            print(
                f"[ActionRouter] 中置信度（{cap_score:.1f}）尝试执行，通知用户可能不完美"
            )
        else:
            await self.blackboard.assign(task, best_agent)

    async def _handle_tool_call(self, tool_spec: dict) -> None:
        result = await self.tool_executor.run(tool_spec)
        print(f"[ActionRouter] tool_call result: {result}")
        await self.event_bus.emit("tool_call_done", {"result": result})

    async def _handle_hitl_relay(self, content: str) -> None:
        result = await self.hitl_gateway.ask_user(content)
        print(f"[ActionRouter] hitl_relay 用户响应: {result}")
        task_id = content.get("task_id") if isinstance(content, dict) else None
        if task_id:
            await self.blackboard.resume(task_id, result)
