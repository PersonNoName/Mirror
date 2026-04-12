from __future__ import annotations

import pytest

from app.platform.base import InboundMessage, PlatformContext
from app.soul.models import Action
from app.soul.router import ActionRouter
from app.tools import ToolInvocationError, ToolRegistry

from tests.conftest import DummyBlackboard, RecordingEventBus, RecordingHookRegistry, RecordingPlatformAdapter


class DummyTaskSystem:
    DISPATCH_STREAM = "stream:task:dispatch"

    @staticmethod
    def stream_for_agent(agent_name: str, base_stream: str | None = None) -> str:
        return f"{base_stream or 'stream'}:{agent_name}"

    @staticmethod
    def group_for_agent(agent_name: str) -> str:
        return f"group:{agent_name}"


def build_message() -> InboundMessage:
    ctx = PlatformContext(platform="web", user_id="user-1", session_id="session-1", capabilities={"streaming"})
    return InboundMessage(text="hello", user_id="user-1", session_id="session-1", platform_ctx=ctx)


@pytest.mark.asyncio
async def test_action_router_routes_direct_reply() -> None:
    platform = RecordingPlatformAdapter()
    event_bus = RecordingEventBus()
    hooks = RecordingHookRegistry()
    router = ActionRouter(
        platform_adapter=platform,
        event_bus=event_bus,
        blackboard=DummyBlackboard(),
        task_system=DummyTaskSystem(),
        tool_registry=ToolRegistry(),
        hook_registry=hooks,
    )

    result = await router.route(
        Action(type="direct_reply", content="hello back", metadata={"brain": {"self_cognition": "x"}}),
        build_message(),
    )

    assert result["reply"] == "hello back"
    assert platform.outbound[0][1].content == "hello back"
    assert result["brain"] == {"self_cognition": "x"}
    assert platform.outbound[0][1].metadata["brain"] == {"self_cognition": "x"}
    assert event_bus.events[0].type == "dialogue_ended"
    assert hooks.calls


@pytest.mark.asyncio
async def test_action_router_finalizes_streamed_direct_reply() -> None:
    platform = RecordingPlatformAdapter()
    router = ActionRouter(
        platform_adapter=platform,
        event_bus=RecordingEventBus(),
        blackboard=DummyBlackboard(),
        task_system=DummyTaskSystem(),
        tool_registry=ToolRegistry(),
    )

    result = await router.route(Action(type="direct_reply", content="hello back", streamed=True), build_message())

    assert result["reply"] == "hello back"
    assert result["streamed"] is True
    assert platform.outbound[0][1].type == "text"
    assert platform.outbound[0][1].metadata == {"streamed": True}


@pytest.mark.asyncio
async def test_action_router_returns_fallback_for_invalid_tool_payload() -> None:
    router = ActionRouter(
        platform_adapter=RecordingPlatformAdapter(),
        event_bus=RecordingEventBus(),
        blackboard=DummyBlackboard(),
        task_system=DummyTaskSystem(),
        tool_registry=ToolRegistry(),
    )

    result = await router.route(Action(type="tool_call", content="not-json"), build_message())

    assert "could not be parsed" in result["reply"]


@pytest.mark.asyncio
async def test_action_router_returns_fallback_for_missing_tool() -> None:
    router = ActionRouter(
        platform_adapter=RecordingPlatformAdapter(),
        event_bus=RecordingEventBus(),
        blackboard=DummyBlackboard(),
        task_system=DummyTaskSystem(),
        tool_registry=ToolRegistry(),
    )

    result = await router.route(
        Action(type="tool_call", content='{"name":"missing_tool","arguments":{"x":1}}'),
        build_message(),
    )

    assert "is not registered" in result["reply"]


@pytest.mark.asyncio
async def test_action_router_returns_tool_output_on_success() -> None:
    registry = ToolRegistry()
    registry.register("echo", lambda params, context: f"echo:{params['value']}")
    router = ActionRouter(
        platform_adapter=RecordingPlatformAdapter(),
        event_bus=RecordingEventBus(),
        blackboard=DummyBlackboard(),
        task_system=DummyTaskSystem(),
        tool_registry=registry,
    )

    result = await router.route(
        Action(type="tool_call", content='{"name":"echo","arguments":{"value":"ok"}}'),
        build_message(),
    )

    assert result["reply"] == "echo:ok"


@pytest.mark.asyncio
async def test_action_router_handles_tool_invocation_error() -> None:
    registry = ToolRegistry()

    def fail(params: dict[str, object], context: object) -> str:
        raise RuntimeError("boom")

    registry.register("fail", fail)
    router = ActionRouter(
        platform_adapter=RecordingPlatformAdapter(),
        event_bus=RecordingEventBus(),
        blackboard=DummyBlackboard(),
        task_system=DummyTaskSystem(),
        tool_registry=registry,
    )

    result = await router.route(
        Action(type="tool_call", content='{"name":"fail","arguments":{}}'),
        build_message(),
    )

    assert "failed: boom" in result["reply"]
