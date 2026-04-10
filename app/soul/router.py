"""Foreground action router."""

from __future__ import annotations

import json
from typing import Any

from app.evolution.event_bus import Event, EventType
from app.hooks import HookPoint
from app.platform.base import HitlRequest, InboundMessage, OutboundMessage
from app.tools import ToolInvocationError
from app.soul.models import Action


class ActionRouter:
    """Route structured soul actions to platform and task subsystems."""

    def __init__(
        self,
        platform_adapter: Any,
        event_bus: Any,
        blackboard: Any,
        task_system: Any,
        tool_registry: Any,
        hook_registry: Any | None = None,
    ) -> None:
        self.platform_adapter = platform_adapter
        self.event_bus = event_bus
        self.blackboard = blackboard
        self.task_system = task_system
        self.tool_registry = tool_registry
        self.hook_registry = hook_registry

    async def route(self, action: Action, inbound_message: InboundMessage) -> dict[str, Any] | None:
        ctx = inbound_message.platform_ctx
        if action.type == "direct_reply":
            await self.platform_adapter.send_outbound(
                ctx,
                OutboundMessage(type="text", content=str(action.content)),
            )
            await self.event_bus.emit(
                Event(
                    type=EventType.DIALOGUE_ENDED,
                    payload={
                        "user_id": inbound_message.user_id,
                        "session_id": inbound_message.session_id,
                        "text": inbound_message.text,
                        "reply": str(action.content),
                    },
                )
            )
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REPLY,
                    message=inbound_message,
                    action=action,
                    reply=str(action.content),
                )
            return {
                "reply": str(action.content),
                "action": action.type,
                "session_id": inbound_message.session_id,
            }

        if action.type == "publish_task":
            task = await self.task_system.create_task_from_action(action, inbound_message)
            best_agent, cap_score = await self.blackboard.evaluate_agents(task)
            if not best_agent or cap_score < 0.3:
                request = HitlRequest(
                    task_id=task.id,
                    title="需要用户确认",
                    description=f"当前工具无法稳妥完成此任务（置信度 {cap_score:.2f}）。",
                )
                await self.blackboard.on_task_waiting_hitl(task, request)
                await self.platform_adapter.send_hitl(ctx, request)
                return {
                    "reply": request.description,
                    "action": "hitl_relay",
                    "task_id": task.id,
                    "session_id": inbound_message.session_id,
                }

            task.assigned_to = best_agent.name
            task.dispatch_stream = self.task_system.stream_for_agent(best_agent.name, self.task_system.DISPATCH_STREAM)
            task.consumer_group = self.task_system.group_for_agent(best_agent.name)
            await self.task_system.update_task(task)
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.PRE_TASK,
                    message=inbound_message,
                    action=action,
                    task=task,
                    capability_score=cap_score,
                )
            if cap_score < 0.5:
                await self.blackboard.assign(task)
                message = (
                    f"正在尝试处理，但置信度偏低（{cap_score:.2f}），"
                    "结果可能需要你确认。"
                )
                await self.platform_adapter.send_outbound(
                    ctx,
                    OutboundMessage(type="text", content=message),
                )
                if self.hook_registry is not None:
                    await self.hook_registry.trigger(
                        HookPoint.POST_REPLY,
                        message=inbound_message,
                        action=action,
                        reply=message,
                        task=task,
                    )
                return {
                    "reply": message,
                    "action": action.type,
                    "task_id": task.id,
                    "session_id": inbound_message.session_id,
                }

            await self.blackboard.assign(task)
            message = "任务已派发，等待异步处理。"
            await self.platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=message))
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REPLY,
                    message=inbound_message,
                    action=action,
                    reply=message,
                    task=task,
                )
            return {
                "reply": message,
                "action": action.type,
                "task_id": task.id,
                "session_id": inbound_message.session_id,
            }

        if action.type == "hitl_relay":
            request = HitlRequest(
                task_id=str(action.metadata.get("task_id", "")),
                title="等待确认",
                description=str(action.content),
            )
            await self.platform_adapter.send_hitl(ctx, request)
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REPLY,
                    message=inbound_message,
                    action=action,
                    reply=request.description,
                    task_id=request.task_id,
                )
            return {
                "reply": request.description,
                "action": action.type,
                "task_id": request.task_id,
                "session_id": inbound_message.session_id,
            }

        if action.type == "tool_call":
            reply = await self._handle_tool_call(action, inbound_message)
            await self.platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=reply))
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REPLY,
                    message=inbound_message,
                    action=action,
                    reply=reply,
                )
            return {
                "reply": reply,
                "action": action.type,
                "session_id": inbound_message.session_id,
            }

        return None

    async def _handle_tool_call(self, action: Action, inbound_message: InboundMessage) -> str:
        try:
            payload = self._parse_tool_payload(action.content)
        except ValueError as exc:
            return f"工具调用解析失败，已降级为直接回复：{exc}"

        tool_name = payload["name"]
        params = payload.get("arguments", {})
        context = {
            "message": inbound_message,
            "platform_context": inbound_message.platform_ctx,
            "action": action,
        }
        try:
            result = await self.tool_registry.invoke(tool_name, params, context=context)
        except KeyError:
            return f"工具 `{tool_name}` 未注册，已降级为直接回复。"
        except ToolInvocationError as exc:
            return f"工具 `{tool_name}` 调用失败：{exc}"

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    @staticmethod
    def _parse_tool_payload(content: Any) -> dict[str, Any]:
        if isinstance(content, dict):
            payload = dict(content)
        elif isinstance(content, str):
            raw = content.strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("tool_call content 必须是 JSON 对象。") from exc
        else:
            raise ValueError("tool_call content 类型无效。")

        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("缺少工具名。")
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("工具 arguments 必须是对象。")
        return {"name": name, "arguments": arguments}
