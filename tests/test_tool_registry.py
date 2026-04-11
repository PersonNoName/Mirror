from __future__ import annotations

import pytest

from app.tools import ToolInvocationError, ToolRegistry


@pytest.mark.asyncio
async def test_tool_registry_invoke_with_params_and_context() -> None:
    registry = ToolRegistry()
    registry.register("two_args", lambda params, context: f"{params['value']}:{context['mode']}")

    result = await registry.invoke("two_args", {"value": "ok"}, context={"mode": "ctx"})

    assert result == "ok:ctx"


@pytest.mark.asyncio
async def test_tool_registry_invoke_with_params_only() -> None:
    registry = ToolRegistry()
    registry.register("one_arg", lambda params: params["value"] * 2)

    result = await registry.invoke("one_arg", {"value": 3})

    assert result == 6


@pytest.mark.asyncio
async def test_tool_registry_invoke_with_no_args() -> None:
    registry = ToolRegistry()
    registry.register("zero_arg", lambda: "done")

    result = await registry.invoke("zero_arg")

    assert result == "done"


@pytest.mark.asyncio
async def test_tool_registry_invoke_supports_async_callables() -> None:
    registry = ToolRegistry()

    async def async_tool(params: dict[str, object], context: dict[str, object]) -> str:
        return f"{params['value']}:{context['mode']}"

    registry.register("async_tool", async_tool)

    result = await registry.invoke("async_tool", {"value": "ok"}, context={"mode": "async"})

    assert result == "ok:async"


@pytest.mark.asyncio
async def test_tool_registry_wraps_callable_failure() -> None:
    registry = ToolRegistry()

    def fail(params: dict[str, object], context: dict[str, object]) -> None:
        raise RuntimeError("boom")

    registry.register("fail", fail)

    with pytest.raises(ToolInvocationError, match="boom"):
        await registry.invoke("fail", {}, context={})
