from abc import ABC, abstractmethod
from domain.task import Task, TaskResult


class SubAgent(ABC):
    name: str
    domain: str

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        pass

    @abstractmethod
    async def estimate_capability(self, task: Task) -> float:
        pass

    async def cancel(self) -> None:
        pass

    async def emit_heartbeat(self, task: Task) -> None:
        raise NotImplementedError("SubAgent must call task_store.update_heartbeat()")
