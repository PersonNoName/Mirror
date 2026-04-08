from abc import ABC, abstractmethod
from typing import Any, Optional
from domain.task import Task
from domain.memory import CoreMemory
from domain.evolution import EvolutionEntry, VectorEntry
from domain.stability import SnapshotRecord


class GraphDBInterface(ABC):
    @abstractmethod
    async def upsert_relation(
        self,
        subject: str,
        relation: str,
        object: str,
        confidence: float,
        is_pinned: bool = False,
    ) -> None:
        pass

    @abstractmethod
    async def get_relation(self, subject: str, object: str) -> Optional[dict]:
        pass

    @abstractmethod
    async def query_user_preferences(self, user_id: str) -> dict:
        pass

    @abstractmethod
    async def query_agent_capabilities(self) -> dict:
        pass

    @abstractmethod
    async def query_env_constraints(self) -> list[str]:
        pass

    @abstractmethod
    async def decay_confidence(
        self,
        relation_type: str,
        half_life_days: int,
    ) -> None:
        pass


class VectorDBInterface(ABC):
    @abstractmethod
    async def insert(self, entry: VectorEntry) -> None:
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        namespace: str,
        top_k: int = 8,
    ) -> list[VectorEntry]:
        pass

    @abstractmethod
    async def delete(self, entry_id: str, namespace: str) -> None:
        pass

    @abstractmethod
    async def update_pinned_status(
        self,
        entry_id: str,
        namespace: str,
        is_pinned: bool,
    ) -> None:
        pass


class TaskStoreInterface(ABC):
    @abstractmethod
    async def create(self, task: Task) -> Task:
        pass

    @abstractmethod
    async def get(self, task_id: str) -> Optional[Task]:
        pass

    @abstractmethod
    async def update(self, task: Task) -> None:
        pass

    @abstractmethod
    async def update_heartbeat(self, task_id: str, timestamp: Any) -> None:
        pass

    @abstractmethod
    async def get_by_status(self, status: str) -> list[Task]:
        pass

    @abstractmethod
    async def get_by_parent(self, parent_task_id: str) -> list[Task]:
        pass


class CoreMemoryStoreInterface(ABC):
    @abstractmethod
    async def get_with_version(self, key: str) -> tuple[dict, int]:
        pass

    @abstractmethod
    async def cas_upsert(
        self,
        key: str,
        value: dict,
        expected_version: int,
    ) -> bool:
        pass

    @abstractmethod
    async def force_upsert(self, key: str, value: dict) -> None:
        pass

    @abstractmethod
    async def get_core_memory(self, user_id: str) -> CoreMemory:
        pass


class JournalStoreInterface(ABC):
    @abstractmethod
    async def append(self, entry: EvolutionEntry) -> None:
        pass

    @abstractmethod
    async def get_recent(self, last_n: int) -> list[EvolutionEntry]:
        pass

    @abstractmethod
    async def get_by_session(self, session_id: str) -> list[EvolutionEntry]:
        pass


class SnapshotStoreInterface(ABC):
    @abstractmethod
    async def save(self, snapshot: SnapshotRecord) -> None:
        pass

    @abstractmethod
    async def get_latest(self, block_type: str) -> Optional[SnapshotRecord]:
        pass

    @abstractmethod
    async def get_history(
        self, block_type: str, limit: int = 5
    ) -> list[SnapshotRecord]:
        pass


class EventBusInterface(ABC):
    @abstractmethod
    async def emit(self, event_type: str, payload: dict) -> None:
        pass

    @abstractmethod
    async def subscribe(self, event_type: str, handler: Any) -> None:
        pass

    @abstractmethod
    async def unsubscribe(self, event_type: str, handler: Any) -> None:
        pass
