"""Tool registry contracts and execution helpers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolDefinition:
    """Structured runtime representation for a registered tool."""

    name: str
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    source: str = "runtime"
    callable: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolInvocationError(RuntimeError):
    """Raised when a registered tool cannot be invoked successfully."""


class ToolRegistry:
    """In-memory tool registry shared by the runtime."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        tool: Any | None = None,
        *,
        description: str = "",
        schema: dict[str, Any] | None = None,
        source: str = "runtime",
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Register a tool directly or return a decorator for later binding."""

        if tool is None:
            def decorator(func: Any) -> Any:
                self._register_definition(
                    name=name,
                    tool=func,
                    description=description or getattr(func, "__doc__", "") or "",
                    schema=schema or {},
                    source=source,
                    metadata=metadata or {},
                )
                return func

            return decorator

        self._register_definition(
            name=name,
            tool=tool,
            description=description,
            schema=schema or {},
            source=source,
            metadata=metadata or {},
        )
        return tool

    def _register_definition(
        self,
        *,
        name: str,
        tool: Any,
        description: str,
        schema: dict[str, Any],
        source: str,
        metadata: dict[str, Any],
    ) -> None:
        if isinstance(tool, ToolDefinition):
            definition = tool
            if not definition.name:
                definition.name = name
            if not definition.source:
                definition.source = source
        else:
            definition = ToolDefinition(
                name=name,
                description=description or getattr(tool, "__doc__", "") or "",
                schema=schema,
                source=source,
                callable=tool,
                metadata=metadata,
            )
        self._tools[name] = definition

    def get(self, name: str) -> ToolDefinition:
        """Return a registered tool definition, raising KeyError if missing."""

        return self._tools[name]

    def list_tools(self) -> list[str]:
        """Return registered tool names in stable sorted order."""

        return sorted(self._tools)

    def describe_tools(self) -> list[dict[str, Any]]:
        """Return structured tool descriptions for prompts or inspection."""

        return [
            {
                "name": definition.name,
                "description": definition.description,
                "schema": definition.schema,
                "source": definition.source,
                "metadata": dict(definition.metadata),
            }
            for definition in sorted(self._tools.values(), key=lambda item: item.name)
        ]

    def items(self) -> list[tuple[str, ToolDefinition]]:
        """Iterate over registered tool pairs."""

        return list(self._tools.items())

    async def invoke(self, name: str, params: dict[str, Any] | None = None, context: Any = None) -> Any:
        """Invoke a registered tool via its callable contract."""

        definition = self.get(name)
        if definition.callable is None:
            raise ToolInvocationError(f"Tool '{name}' has no callable implementation.")

        params = params or {}
        try:
            result = definition.callable(params, context)
        except TypeError:
            try:
                result = definition.callable(params)
            except TypeError:
                result = definition.callable()
        except Exception as exc:
            raise ToolInvocationError(str(exc)) from exc

        if inspect.isawaitable(result):
            try:
                return await result
            except Exception as exc:
                raise ToolInvocationError(str(exc)) from exc
        return result


tool_registry = ToolRegistry()
