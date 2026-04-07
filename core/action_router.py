from typing import Optional, TypedDict

from domain.task import Task


class RouteResult(TypedDict):
    action: str
    content: str
    task_id: Optional[str]


class TaskSystemDummy:
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
    async def ask_user(self, message: str) -> dict:
        print(f"[HITLGatewayDummy] 请求用户确认: {message}")
        return {"approved": True, "result": "用户确认"}


class ToolExecutorDummy:
    async def run(self, tool_spec: dict) -> dict:
        print(f"[ToolExecutorDummy] 执行工具: {tool_spec}")
        return {"success": True, "result": "工具执行结果"}


class EventBusDummy:
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

    async def route(
        self, action_output: dict, context: Optional[dict] = None
    ) -> RouteResult:
        action_type = action_output.get("action", "direct_reply")
        content = action_output.get("content", "")
        ctx = context or {}

        match action_type:
            case "direct_reply":
                return await self._handle_direct_reply(content)
            case "publish_task":
                return await self._handle_publish_task(content, ctx)
            case "tool_call":
                return await self._handle_tool_call(content)
            case "hitl_relay":
                return await self._handle_hitl_relay(content)
            case _:
                print(f"[ActionRouter] 未知动作类型: {action_type}, 默认 direct_reply")
                return RouteResult(
                    action="direct_reply",
                    content=content or "无法处理该请求。",
                    task_id=None,
                )

    async def _handle_direct_reply(self, content: str) -> RouteResult:
        print(f"[ActionRouter] direct_reply: {content[:100]}...")
        await self.event_bus.emit("dialogue_ended", {"reply": content})
        return RouteResult(
            action="direct_reply",
            content=content,
            task_id=None,
        )

    async def _handle_publish_task(self, task_spec: dict, context: dict) -> RouteResult:
        task_id = task_spec.get("task_id")
        user_id = context.get("user_id", "")

        if task_id:
            task = await self.task_system.get(task_id)
            if not task:
                print(f"[ActionRouter] 发布任务失败：任务 {task_id} 不存在")
                return RouteResult(
                    action="publish_task",
                    content=f"任务 {task_id} 不存在",
                    task_id=None,
                )
        else:
            intent = task_spec.get("intent", "")
            if not intent:
                print("[ActionRouter] 发布任务失败：intent 为空")
                return RouteResult(
                    action="publish_task",
                    content="任务描述为空",
                    task_id=None,
                )
            task = await self.task_system.create(
                {
                    "intent": intent,
                    "prompt_snapshot": task_spec.get("prompt_snapshot", ""),
                    "priority": task_spec.get("priority", 1),
                    "depends_on": task_spec.get("depends_on", []),
                    "metadata": {"user_id": user_id},
                }
            )
            print(f"[ActionRouter] 发布新任务: {task.id} - {intent}")

        best_agent, cap_score = await self.blackboard.evaluate_agents(task)

        if cap_score < 0.3:
            fallback_msg = (
                f"当前工具无法稳妥完成此任务（置信度 {cap_score}），请求指示。"
            )
            result = await self.hitl_gateway.ask_user(fallback_msg)
            print(f"[ActionRouter] 低置信度 HITL: {fallback_msg}")
            await self.blackboard.resume(task.id, result)
            return RouteResult(
                action="publish_task",
                content=fallback_msg,
                task_id=task.id,
            )
        elif cap_score < 0.5:
            print(
                f"[ActionRouter] 中置信度（{cap_score:.1f}）尝试执行，通知用户可能不完美"
            )
            await self.blackboard.assign(task, best_agent)
            return RouteResult(
                action="publish_task",
                content=f"任务已提交执行（置信度 {cap_score}），结果可能不完美。",
                task_id=task.id,
            )
        else:
            await self.blackboard.assign(task, best_agent)
            print(f"[ActionRouter] 高置信度（{cap_score:.1f}）直接执行")
            return RouteResult(
                action="publish_task",
                content="任务已提交执行。",
                task_id=task.id,
            )

    async def _handle_tool_call(self, tool_spec: dict) -> RouteResult:
        tool_name = tool_spec.get("name", "unknown")
        print(f"[ActionRouter] tool_call: {tool_name}")
        result = await self.tool_executor.run(tool_spec)
        await self.event_bus.emit("tool_call_done", {"result": result})
        return RouteResult(
            action="tool_call",
            content=str(result),
            task_id=None,
        )

    async def _handle_hitl_relay(self, content: str) -> RouteResult:
        if isinstance(content, dict):
            message = content.get("message", str(content))
            task_id = content.get("task_id")
        else:
            message = str(content)
            task_id = None

        print(f"[ActionRouter] hitl_relay: 请求用户确认 - {message[:80]}...")
        result = await self.hitl_gateway.ask_user(message)

        if task_id:
            await self.blackboard.resume(task_id, result)

        return RouteResult(
            action="hitl_relay",
            content=str(result),
            task_id=task_id,
        )
