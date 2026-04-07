import asyncio

from domain.memory import CoreMemory
from domain.evolution import Event, EvolutionEntry

from core.memory_cache import CoreMemoryCache
from core.vector_retriever import VectorRetriever, EmbedderDummy
from core.soul_engine import SoulEngine
from core.action_router import (
    ActionRouter,
    HITLGatewayDummy,
    ToolExecutorDummy,
)
from core.blackboard import Blackboard
from core.task_system import TaskSystem
from core.code_agent import CodeAgent
from core.core_memory_scheduler import CoreMemoryScheduler

from events.event_bus import EventBus, EVENT_BUS_CONFIG
from evolution.signal_extractor import SignalExtractor
from evolution.personality_evolver import PersonalityEvolver
from evolution.cognition_updater import CognitionUpdater
from evolution.evolution_journal import EvolutionJournal
from evolution.meta_cognition import MetaCognitionReflector
from evolution.observer import ObserverEngine

from services.graph_db import GraphDBClient
from services.vector_db import VectorDBClient


class LLMInterfaceDummy:
    async def generate(self, prompt: str) -> str:
        return f"[LLM Mock Response to: {prompt[:50]}...]"

    async def generate_json(self, prompt: str) -> dict:
        return {"confidence": 0.6, "root_cause": "mock", "lesson": "mock"}


class JournalStoreDummy:
    def __init__(self):
        self._entries: list[EvolutionEntry] = []

    async def append(self, entry: EvolutionEntry) -> None:
        self._entries.append(entry)

    async def get_recent(self, last_n: int) -> list[EvolutionEntry]:
        return self._entries[-last_n:] if self._entries else []

    async def get_by_session(self, session_id: str) -> list[EvolutionEntry]:
        return [e for e in self._entries if e.session_id == session_id]


class TaskStoreDummy:
    def __init__(self):
        self._tasks: dict[str, object] = {}
        self._user_ids: list[str] = []

    async def create(self, task):
        self._tasks[task.id] = task
        return task

    async def get(self, task_id: str):
        return self._tasks.get(task_id)

    async def update(self, task) -> None:
        self._tasks[task.id] = task

    async def update_heartbeat(self, task_id: str, timestamp: object) -> None:
        if task_id in self._tasks:
            self._tasks[task_id].last_heartbeat_at = timestamp

    async def get_by_status(self, status: str) -> list:
        return [t for t in self._tasks.values() if t.status == status]

    async def get_by_parent(self, parent_task_id: str) -> list:
        return [t for t in self._tasks.values() if t.parent_task_id == parent_task_id]

    async def get_all_user_ids(self) -> list[str]:
        return self._user_ids


class CoreMemoryStoreDummy:
    def __init__(self):
        self._data: dict[str, tuple[dict, int]] = {}

    async def get_with_version(self, key: str) -> tuple[dict, int]:
        if key in self._data:
            return self._data[key]
        return {}, 0

    async def cas_upsert(self, key: str, value: dict, expected_version: int) -> bool:
        if key in self._data:
            _, version = self._data[key]
            if version != expected_version:
                return False
        self._data[key] = (value, expected_version + 1)
        return True

    async def force_upsert(self, key: str, value: dict) -> None:
        current = self._data.get(key, ({}, 0))
        self._data[key] = (value, current[1] + 1)

    async def get_core_memory(self, user_id: str) -> CoreMemory:
        return CoreMemory()


class AgentApplication:
    def __init__(self):
        self._running = False

    async def initialize(self) -> None:
        self.llm = LLMInterfaceDummy()
        self.task_store = TaskStoreDummy()
        self.core_memory_store = CoreMemoryStoreDummy()
        self.journal_store = JournalStoreDummy()

        self.core_memory_cache = CoreMemoryCache()
        self.vector_retriever = VectorRetriever(
            embedder=EmbedderDummy(),
            vector_db=VectorDBClient(),
        )
        self.graph_db = GraphDBClient()
        self.vector_db = VectorDBClient()

        self.event_bus = EventBus(EVENT_BUS_CONFIG)

        self.blackboard = Blackboard(
            task_store=self.task_store,
            event_bus=self.event_bus,
            agent_registry={},
        )

        self.task_system = TaskSystem(
            task_store=self.task_store,
            blackboard=self.blackboard,
        )

        self.code_agent = CodeAgent(
            task_store=self.task_store,
            blackboard=self.blackboard,
            core_memory_cache=self.core_memory_cache,
        )
        self.blackboard.register_agent(self.code_agent)

        self.core_memory_scheduler = CoreMemoryScheduler(
            core_memory_store=self.core_memory_store,
            cache=self.core_memory_cache,
            llm=self.llm,
        )

        self.soul_engine = SoulEngine(
            core_memory_cache=self.core_memory_cache,
            vector_retriever=self.vector_retriever,
            llm=self.llm,
        )

        self.evolution_journal = EvolutionJournal(
            journal_store=self.journal_store,
            llm_lite=self.llm,
        )

        self.signal_extractor = SignalExtractor()

        self.personality_evolver = PersonalityEvolver(
            core_memory_cache=self.core_memory_cache,
            llm_lite=self.llm,
            evolution_journal=self.evolution_journal,
            graph_db=self.graph_db,
            core_memory_scheduler=self.core_memory_scheduler,
        )

        self.cognition_updater = CognitionUpdater(
            core_memory_cache=self.core_memory_cache,
            graph_db=self.graph_db,
            core_memory_scheduler=self.core_memory_scheduler,
        )

        self.meta_cognition = MetaCognitionReflector(llm_lite=self.llm)

        self.observer = ObserverEngine(
            graph_db=self.graph_db,
            vector_db=self.vector_db,
            llm_lite=self.llm,
        )

        self.action_router = ActionRouter(
            task_system=self.task_system,
            blackboard=self.blackboard,
            hitl_gateway=HITLGatewayDummy(),
            tool_executor=ToolExecutorDummy(),
            event_bus=self.event_bus,
        )

        await self._setup_event_subscriptions()
        await self.event_bus.start()
        await self.task_system.start()

        asyncio.create_task(self._task_worker_loop())
        asyncio.create_task(self._slow_evolution_loop())

        await self._load_core_memory()

        self._running = True
        print("[AgentApplication] 初始化完成")

    async def _task_worker_loop(self) -> None:
        print("[AgentApplication] task_worker_loop started")
        while self._running:
            task = await self.task_system.queue.dequeue()
            if task:
                await self.blackboard.assign(task)
            else:
                await asyncio.sleep(0.1)
        print("[AgentApplication] task_worker_loop stopped")

    async def _get_all_user_ids(self) -> list[str]:
        if hasattr(self.task_store, "get_all_user_ids"):
            return await self.task_store.get_all_user_ids()
        print(
            "[AgentApplication] TaskStore does not implement get_all_user_ids, skipping memory load"
        )
        return []

    async def _get_active_users(self) -> list[str]:
        return await self._get_all_user_ids()

    def _collect_pending_signals(self, user_id: str) -> list:
        signals = []
        for tag, sigs in getattr(
            self.personality_evolver, "_signal_buffer", {}
        ).items():
            signals.extend(sigs)
        signals.sort(key=lambda s: s.turn_index, reverse=True)
        return signals[:10]

    async def _load_core_memory(self) -> None:
        user_ids = await self._get_all_user_ids()
        if not user_ids:
            print("[AgentApplication] No user IDs found, skipping core memory load")
            return

        for user_id in user_ids:
            memory = await self.core_memory_store.get_core_memory(user_id)
            self.core_memory_cache.set(user_id, memory)
            print(f"[AgentApplication] Loaded core memory for user: {user_id}")

    async def _slow_evolution_loop(self) -> None:
        SLOW_EVOLVE_INTERVAL = 3600
        SLOW_EVOLVE_SESSION_THRESHOLD = 10
        session_counter = 0
        print("[AgentApplication] slow_evolution_loop started")
        while self._running:
            await asyncio.sleep(SLOW_EVOLVE_INTERVAL)
            session_counter += 1
            if session_counter >= SLOW_EVOLVE_SESSION_THRESHOLD:
                session_counter = 0
                user_ids = await self._get_active_users()
                for user_id in user_ids:
                    signals = self._collect_pending_signals(user_id)
                    await self.personality_evolver.slow_evolve(signals, user_id)
                    print(
                        f"[AgentApplication] slow_evolve completed for user: {user_id}"
                    )
        print("[AgentApplication] slow_evolution_loop stopped")

    async def _setup_event_subscriptions(self) -> None:
        async def handle_dialogue_ended(event: Event) -> None:
            dialogue = event.payload.get("dialogue", [])
            session_id = event.payload.get("session_id", "")
            user_id = event.payload.get("user_id", "")

            signals = await self.signal_extractor.extract(
                dialogue, session_id, turn_index=0
            )
            for signal in signals:
                await self.personality_evolver.fast_adapt(signal, user_id)

            await self.observer.process(dialogue, session_id)

        async def handle_task_completed(event: Event) -> None:
            task_data = event.payload.get("task")
            if not task_data:
                return

            from domain.task import Task

            task = Task(**task_data)
            lesson = await self.meta_cognition.reflect(task)
            if lesson:
                await self.cognition_updater.update(
                    lesson, event.payload.get("user_id", "")
                )

        async def handle_task_failed(event: Event) -> None:
            task_data = event.payload.get("task")
            if not task_data:
                return

            from domain.task import Task

            task = Task(**task_data)
            lesson = await self.meta_cognition.reflect(task)
            if lesson:
                await self.cognition_updater.update(
                    lesson, event.payload.get("user_id", "")
                )

        await self.event_bus.subscribe("dialogue_ended", handle_dialogue_ended)
        await self.event_bus.subscribe("task_completed", handle_task_completed)
        await self.event_bus.subscribe("task_failed", handle_task_failed)

    async def run(self) -> None:
        print("[AgentApplication] 运行中...")
        while self._running:
            await asyncio.sleep(1)

    async def shutdown(self) -> None:
        self._running = False
        await self.task_system.stop()
        await self.event_bus.stop()
        print("[AgentApplication] 已关闭")


async def main() -> None:
    app = AgentApplication()
    await app.initialize()
    print("[AgentApplication] 初始化完成，模拟运行测试...")

    await app.event_bus.emit(
        "dialogue_ended",
        {
            "user_id": "test_user",
            "session_id": "test_session",
            "dialogue": [
                {"role": "user", "content": "请简洁回复"},
                {"role": "assistant", "content": "好的，我会简洁回复。"},
            ],
        },
    )

    await asyncio.sleep(0.5)
    await app.shutdown()
    print("[AgentApplication] 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
