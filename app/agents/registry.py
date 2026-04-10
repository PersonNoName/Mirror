"""Global sub-agent registry."""

from __future__ import annotations

from app.agents.base import SubAgent


class AgentRegistry:
    """In-memory registry for sub-agent instances."""

    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> SubAgent | None:
        return self._agents.get(name)

    def all(self) -> list[SubAgent]:
        return list(self._agents.values())


agent_registry = AgentRegistry()
