"""Global sub-agent registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from app.agents.base import SubAgent


logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class AgentRegistration:
    """Structured runtime representation for registered agents."""

    agent: SubAgent
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)


class AgentRegistry:
    """In-memory registry for sub-agent instances."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentRegistration] = {}

    def register(
        self,
        agent: SubAgent,
        *,
        source: str = "runtime",
        overwrite: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> SubAgent:
        existing = self._agents.get(agent.name)
        if existing is not None and not overwrite:
            logger.info(
                "agent_registration_skipped",
                agent_name=agent.name,
                existing_source=existing.source,
                incoming_source=source,
            )
            return existing.agent
        self._agents[agent.name] = AgentRegistration(
            agent=agent,
            source=source,
            metadata=metadata or {},
        )
        return agent

    def get(self, name: str) -> SubAgent | None:
        registration = self._agents.get(name)
        if registration is None:
            return None
        return registration.agent

    def get_registration(self, name: str) -> AgentRegistration | None:
        return self._agents.get(name)

    def all(self) -> list[SubAgent]:
        return [registration.agent for registration in self._agents.values()]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": registration.agent.name,
                "domain": registration.agent.domain,
                "source": registration.source,
                "metadata": dict(registration.metadata),
            }
            for registration in sorted(self._agents.values(), key=lambda item: item.agent.name)
        ]


agent_registry = AgentRegistry()
