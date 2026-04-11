from __future__ import annotations

import asyncio

import pytest

from app.platform.base import InboundMessage, PlatformContext
from app.soul.models import Action
from app.tasks.models import Task
from app.tasks.task_system import TaskSystem

from tests.conftest import DummyOutboxStore, DummyTaskStore


def build_message() -> InboundMessage:
    ctx = PlatformContext(platform="web", user_id="user-1", session_id="session-1")
    return InboundMessage(text="hello", user_id="user-1", session_id="session-1", platform_ctx=ctx)


@pytest.mark.asyncio
async def test_task_system_creates_task_from_action() -> None:
    task_store = DummyTaskStore()
    system = TaskSystem(task_store=task_store, outbox_store=DummyOutboxStore())

    task = await system.create_task_from_action(Action(type="publish_task", content="do it"), build_message())

    assert task.intent == "do it"
    assert task.metadata["user_id"] == "user-1"
    assert task_store.created


@pytest.mark.asyncio
async def test_wait_for_hitl_response_returns_existing_response_immediately() -> None:
    system = TaskSystem(task_store=DummyTaskStore(), outbox_store=DummyOutboxStore())
    await system.register_hitl_response("task-1", "approve", {"a": 1})

    response = await system.wait_for_hitl_response("task-1")

    assert response == {"decision": "approve", "payload": {"a": 1}}
    assert "task-1" not in system.waiting_hitl


@pytest.mark.asyncio
async def test_wait_for_hitl_response_resolves_after_async_registration() -> None:
    system = TaskSystem(task_store=DummyTaskStore(), outbox_store=DummyOutboxStore())

    async def register_later() -> None:
        await asyncio.sleep(0.01)
        await system.register_hitl_response("task-2", "reject", {"reason": "no"})

    async with asyncio.TaskGroup() as tg:
        tg.create_task(register_later())
        response = await system.wait_for_hitl_response("task-2", timeout_seconds=1)

    assert response == {"decision": "reject", "payload": {"reason": "no"}}
    assert "task-2" not in system._hitl_waiters


@pytest.mark.asyncio
async def test_wait_for_hitl_response_cleans_waiter_after_timeout() -> None:
    system = TaskSystem(task_store=DummyTaskStore(), outbox_store=DummyOutboxStore())

    with pytest.raises(asyncio.TimeoutError):
        await system.wait_for_hitl_response("task-3", timeout_seconds=0.01)

    assert "task-3" not in system._hitl_waiters
