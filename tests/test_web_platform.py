from __future__ import annotations

import pytest

from app.platform.base import HitlRequest, OutboundMessage, PlatformContext
from app.platform.web import WebPlatformAdapter


@pytest.mark.asyncio
async def test_normalize_inbound_populates_context() -> None:
    adapter = WebPlatformAdapter()

    inbound = await adapter.normalize_inbound(
        {
            "text": "hello",
            "session_id": "session-1",
            "user_id": "user-1",
            "capabilities": ["streaming"],
            "metadata": {"k": "v"},
        }
    )

    assert inbound.text == "hello"
    assert inbound.user_id == "user-1"
    assert inbound.platform_ctx.platform == "web"
    assert "streaming" in inbound.platform_ctx.capabilities


@pytest.mark.asyncio
async def test_send_outbound_emits_delta_message_done_for_streaming() -> None:
    adapter = WebPlatformAdapter()
    queue = adapter.subscribe("session-1")
    ctx = PlatformContext(platform="web", user_id="user-1", session_id="session-1", capabilities={"streaming"})

    await adapter.send_outbound(ctx, OutboundMessage(type="text", content="hello world"))

    events = [await queue.get(), await queue.get(), await queue.get()]
    assert events[0]["event"] == "delta"
    assert events[1]["event"] == "message"
    assert events[2] == {"event": "done", "data": {"status": "done"}}


@pytest.mark.asyncio
async def test_send_outbound_emits_message_done_for_non_streaming() -> None:
    adapter = WebPlatformAdapter()
    queue = adapter.subscribe("session-2")
    ctx = PlatformContext(platform="web", user_id="user-1", session_id="session-2")

    await adapter.send_outbound(ctx, OutboundMessage(type="text", content="hello"))

    events = [await queue.get(), await queue.get()]
    assert [event["event"] for event in events] == ["message", "done"]


@pytest.mark.asyncio
async def test_send_hitl_emits_hitl_message_and_waiting_state() -> None:
    adapter = WebPlatformAdapter()
    queue = adapter.subscribe("session-3")
    ctx = PlatformContext(platform="web", user_id="user-1", session_id="session-3")

    await adapter.send_hitl(
        ctx,
        HitlRequest(task_id="task-1", title="Need approval", description="approve this"),
    )

    events = [await queue.get(), await queue.get()]
    assert events[0]["data"]["type"] == "hitl_request"
    assert events[0]["data"]["metadata"]["task_id"] == "task-1"
    assert events[1] == {"event": "done", "data": {"status": "waiting_hitl"}}
