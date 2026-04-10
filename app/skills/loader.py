"""Manifest-driven skill loader for tools, hooks, and sub-agents."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import structlog

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - optional dependency path
    yaml = None

from app.agents.registry import AgentRegistry
from app.hooks.registry import HookPoint, HookRegistry
from app.tools.registry import ToolRegistry


logger = structlog.get_logger(__name__)


class SkillLoader:
    """Load local skill manifests and register their exported runtime objects."""

    def __init__(
        self,
        *,
        skills_dir: str = "skills",
        tool_registry: ToolRegistry,
        hook_registry: HookRegistry,
        agent_registry: AgentRegistry,
    ) -> None:
        self.skills_dir = Path(skills_dir)
        self.tool_registry = tool_registry
        self.hook_registry = hook_registry
        self.agent_registry = agent_registry
        self.load_summary: dict[str, Any] = {"loaded": [], "skipped": [], "failed": []}

    def load_all(self) -> dict[str, Any]:
        """Load every JSON/YAML manifest in the skills directory."""

        summary = {"loaded": [], "skipped": [], "failed": []}
        if not self.skills_dir.exists():
            summary["skipped"].append({"path": str(self.skills_dir), "reason": "missing_directory"})
            self.load_summary = summary
            return summary

        for path in sorted(self.skills_dir.glob("**/*")):
            if path.suffix.lower() not in {".json", ".yaml", ".yml"} or not path.is_file():
                continue
            try:
                manifest = self._read_manifest(path)
                self._register_manifest(path, manifest)
                summary["loaded"].append({"path": str(path), "type": manifest.get("type", "")})
            except Exception as exc:
                summary["failed"].append({"path": str(path), "reason": str(exc)})
                logger.warning("skill_manifest_failed", path=str(path), reason=str(exc))

        self.load_summary = summary
        return summary

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        raw = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(raw)
        else:
            if yaml is None:
                raise RuntimeError("PyYAML is required to load YAML skill manifests.")
            data = yaml.safe_load(raw)
        if not isinstance(data, dict):
            raise ValueError("Skill manifest must be an object.")
        return data

    def _register_manifest(self, path: Path, manifest: dict[str, Any]) -> None:
        manifest_type = str(manifest.get("type", "")).strip()
        if manifest_type == "tool":
            self._register_tool(path, manifest)
            return
        if manifest_type == "hook":
            self._register_hook(path, manifest)
            return
        if manifest_type == "sub_agent":
            self._register_agent(path, manifest)
            return
        raise ValueError(f"Unsupported skill manifest type: {manifest_type or '<empty>'}")

    def _register_tool(self, path: Path, manifest: dict[str, Any]) -> None:
        name = str(manifest.get("name", "")).strip()
        target = str(manifest.get("target", "")).strip()
        if not name or not target:
            raise ValueError("Tool manifest requires 'name' and 'target'.")
        callable_obj = self._resolve_target(target)
        self.tool_registry.register(
            name=name,
            tool=callable_obj,
            description=str(manifest.get("description", "")),
            schema=dict(manifest.get("schema", {}) or {}),
            source=f"skill:{path.stem}",
            metadata={"manifest_path": str(path)},
        )

    def _register_hook(self, path: Path, manifest: dict[str, Any]) -> None:
        hook_point_raw = str(manifest.get("hook_point", "")).strip()
        target = str(manifest.get("target", "")).strip()
        if not hook_point_raw or not target:
            raise ValueError("Hook manifest requires 'hook_point' and 'target'.")
        hook_point = HookPoint(hook_point_raw)
        handler = self._resolve_target(target)
        self.hook_registry.register(
            hook_point,
            handler,
            source=f"skill:{path.stem}",
            metadata={"manifest_path": str(path)},
        )

    def _register_agent(self, path: Path, manifest: dict[str, Any]) -> None:
        target = str(manifest.get("target", "")).strip()
        if not target:
            raise ValueError("Sub-agent manifest requires 'target'.")
        agent = self._resolve_target(target)
        if callable(agent) and not hasattr(agent, "execute"):
            agent = agent()
        if not hasattr(agent, "execute") or not hasattr(agent, "estimate_capability"):
            raise ValueError("Resolved sub-agent target does not satisfy SubAgent contract.")
        overwrite = bool(manifest.get("overwrite", True))
        self.agent_registry.register(
            agent,
            source=f"skill:{path.stem}",
            overwrite=overwrite,
            metadata={"manifest_path": str(path)},
        )

    @staticmethod
    def _resolve_target(target: str) -> Any:
        module_name, _, attr_path = target.partition(":")
        if not module_name or not attr_path:
            raise ValueError(f"Invalid target reference: {target}")
        module = importlib.import_module(module_name)
        value: Any = module
        for part in attr_path.split("."):
            value = getattr(value, part)
        return value
