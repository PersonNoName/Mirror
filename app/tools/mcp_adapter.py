"""Minimal MCP tool adapter for V1 registration and forwarding."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog

from app.tools.registry import ToolRegistry


logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 10.0


class MCPToolAdapter:
    """Load MCP tools from configured servers and register them locally."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        servers_file: str = "mcp_servers.json",
        servers_json: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.tool_registry = tool_registry
        self.servers_file = servers_file
        self.servers_json = servers_json
        self.transport = transport
        self.load_summary: dict[str, Any] = {"loaded": [], "skipped": [], "failed": []}

    async def load_all(self) -> dict[str, Any]:
        """Load tools from all configured MCP servers."""

        summary = {"loaded": [], "skipped": [], "failed": []}
        for server in self._read_server_configs():
            try:
                tools = await self._list_tools(server)
            except Exception as exc:
                summary["failed"].append({"server": server.name, "reason": str(exc)})
                logger.warning("mcp_server_load_failed", server=server.name, reason=str(exc))
                continue

            for tool in tools:
                tool_name = str(tool.get("name", "")).strip()
                if not tool_name:
                    summary["skipped"].append({"server": server.name, "reason": "missing_tool_name"})
                    continue
                self.tool_registry.register(
                    name=tool_name,
                    tool=self._build_proxy(server, tool_name),
                    description=str(tool.get("description", "")),
                    schema=dict(tool.get("inputSchema", {}) or {}),
                    source=f"mcp:{server.name}",
                    metadata={"server": server.name, "server_url": server.url, "tool_name": tool_name},
                )
                summary["loaded"].append({"server": server.name, "tool": tool_name})

        self.load_summary = summary
        return summary

    def _read_server_configs(self) -> list[MCPServerConfig]:
        configs: list[dict[str, Any]] = []
        if self.servers_json.strip():
            try:
                payload = json.loads(self.servers_json)
                if isinstance(payload, dict):
                    configs.extend(payload.get("servers", []))
                elif isinstance(payload, list):
                    configs.extend(payload)
            except json.JSONDecodeError as exc:
                logger.warning("mcp_servers_json_invalid", reason=str(exc))

        path = Path(self.servers_file)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                logger.warning("mcp_servers_file_invalid", path=str(path), reason=str(exc))
            else:
                if isinstance(payload, dict):
                    configs.extend(payload.get("servers", []))
                elif isinstance(payload, list):
                    configs.extend(payload)

        result: list[MCPServerConfig] = []
        for item in configs:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            url = str(item.get("url", "")).strip()
            if not name or not url:
                continue
            result.append(
                MCPServerConfig(
                    name=name,
                    url=url,
                    headers={str(k): str(v) for k, v in dict(item.get("headers", {})).items()},
                    timeout_seconds=float(item.get("timeout_seconds", 10.0)),
                )
            )
        return result

    async def _list_tools(self, server: MCPServerConfig) -> list[dict[str, Any]]:
        payload = await self._post(server, {"jsonrpc": "2.0", "id": "tools-list", "method": "tools/list", "params": {}})
        result = payload.get("result", {})
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            return []
        return [tool for tool in tools if isinstance(tool, dict)]

    def _build_proxy(self, server: MCPServerConfig, tool_name: str):
        async def invoke(params: dict[str, Any], context: Any | None = None) -> Any:
            del context
            payload = await self._post(
                server,
                {
                    "jsonrpc": "2.0",
                    "id": f"tools-call:{tool_name}",
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": params or {}},
                },
            )
            return payload.get("result", {})

        return invoke

    async def _post(self, server: MCPServerConfig, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(
            transport=self.transport,
            timeout=server.timeout_seconds,
            headers=server.headers,
        ) as client:
            response = await client.post(server.url, json=payload)
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                raise RuntimeError(str(data["error"]))
            if not isinstance(data, dict):
                raise RuntimeError("MCP server returned non-object response.")
            return data
