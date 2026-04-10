"""Foreground action router."""

from __future__ import annotations

from typing import Any

from app.evolution.event_bus import Event, EventType
from app.platform.base import HitlRequest, InboundMessage, OutboundMessage
from app.soul.models import Action
from app.tasks.models import Task


class ActionRouter:
    """Route structured soul actions to platform and task subsystems."""

    def __init__(
        self,
        platform_adapter: Any,
        event_bus: Any,
        blackboard: Any,
        task_system: Any,
    ) -> None:
        self.platform_adapter = platform_adapter
        self.event_bus = event_bus
        self.blackboard = blackboard
        self.task_system = task_system

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
            await self.task_system.update_task(task)
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
                return {
                    "reply": message,
                    "action": action.type,
                    "task_id": task.id,
                    "session_id": inbound_message.session_id,
                }

            await self.blackboard.assign(task)
            message = "任务已派发，等待异步处理。"
            await self.platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=message))
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
            return {
                "reply": request.description,
                "action": action.type,
                "task_id": request.task_id,
                "session_id": inbound_message.session_id,
            }

        if action.type == "tool_call":
            fallback = "工具调用尚未在 Phase 4 实现，已改为直接回复。"
            await self.platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=fallback))
            return {
                "reply": fallback,
                "action": "direct_reply",
                "session_id": inbound_message.session_id,
            }

        return None
