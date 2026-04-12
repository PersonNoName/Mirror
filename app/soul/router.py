"""Foreground action router."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.evolution.event_bus import Event, EventType
from app.hooks import HookPoint
from app.platform.base import HitlRequest, InboundMessage, OutboundMessage
from app.soul.models import Action
from app.tools import ToolInvocationError


logger = structlog.get_logger(__name__)


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
        trace_service: Any | None = None,
    ) -> None:
        self.platform_adapter = platform_adapter
        self.event_bus = event_bus
        self.blackboard = blackboard
        self.task_system = task_system
        self.tool_registry = tool_registry
        self.hook_registry = hook_registry
        self.trace_service = trace_service

    async def route(self, action: Action, inbound_message: InboundMessage) -> dict[str, Any] | None:
        ctx = inbound_message.platform_ctx
        await self._trace(
            inbound_message,
            "routing",
            "Action router received action",
            {"action_type": action.type},
        )
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
            await self._trace(
                inbound_message,
                "routing",
                "Direct reply delivered to platform",
                {"reply_preview": str(action.content)[:200]},
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
                    title="User confirmation required",
                    description=(
                        "No available agent can reliably complete this task. "
                        f"Capability score={cap_score:.2f}."
                    ),
                )
                await self.blackboard.on_task_waiting_hitl(task, request)
                await self.platform_adapter.send_hitl(ctx, request)
                await self._trace(
                    inbound_message,
                    "routing",
                    "Task downgraded to HITL because no agent could execute it reliably",
                    {"task_id": task.id, "capability_score": cap_score},
                )
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
            await self._trace(
                inbound_message,
                "routing",
                "Task assigned to agent",
                {"task_id": task.id, "agent": best_agent.name, "capability_score": cap_score},
            )
            if cap_score < 0.5:
                await self.blackboard.assign(task)
                message = (
                    "Task dispatch started, but the selected agent has low confidence "
                    f"(score={cap_score:.2f}). The result may need review."
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
                await self._trace(
                    inbound_message,
                    "routing",
                    "Low-confidence task dispatch reply delivered",
                    {"task_id": task.id, "reply_preview": message[:200]},
                )
                return {
                    "reply": message,
                    "action": action.type,
                    "task_id": task.id,
                    "session_id": inbound_message.session_id,
                }

            await self.blackboard.assign(task)
            message = "Task dispatched. Waiting for asynchronous execution."
            await self.platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=message))
            if self.hook_registry is not None:
                await self.hook_registry.trigger(
                    HookPoint.POST_REPLY,
                    message=inbound_message,
                    action=action,
                    reply=message,
                    task=task,
                )
            await self._trace(
                inbound_message,
                "routing",
                "Task dispatch reply delivered",
                {"task_id": task.id, "reply_preview": message[:200]},
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
                title="Waiting for confirmation",
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
            await self._trace(
                inbound_message,
                "routing",
                "HITL request delivered to platform",
                {"task_id": request.task_id, "reply_preview": request.description[:200]},
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
            await self._trace(
                inbound_message,
                "routing",
                "Tool-call reply delivered to platform",
                {"reply_preview": reply[:200]},
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
            return f"Tool call payload could not be parsed. Falling back to direct reply: {exc}"

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
            logger.warning(
                "tool_invocation_failed",
                tool_name=tool_name,
                reason="not_registered",
            )
            return f"Tool `{tool_name}` is not registered. Falling back to direct reply."
        except ToolInvocationError as exc:
            logger.warning(
                "tool_invocation_failed",
                tool_name=tool_name,
                reason="invocation_error",
                error=str(exc),
            )
            return f"Tool `{tool_name}` failed: {exc}"

        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)

    async def _trace(
        self,
        inbound_message: InboundMessage,
        step_type: str,
        title: str,
        data: dict[str, Any],
    ) -> None:
        if self.trace_service is None:
            return
        await self.trace_service.add_step(
            inbound_message.session_id,
            step_type=step_type,
            title=title,
            data=data,
        )

    @staticmethod
    def _parse_tool_payload(content: Any) -> dict[str, Any]:
        if isinstance(content, dict):
            payload = dict(content)
        elif isinstance(content, str):
            raw = content.strip()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("tool_call content must be a JSON object.") from exc
        else:
            raise ValueError("tool_call content has an invalid type.")

        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("tool_call content is missing a tool name.")
        arguments = payload.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("tool_call arguments must be an object.")
        return {"name": name, "arguments": arguments}
