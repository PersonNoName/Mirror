import asyncio
import os
from typing import Optional, Any

from domain.memory import CoreMemory
from domain.evolution import Event, EvolutionEntry, Lesson

from core.memory_cache import CoreMemoryCache
from core.vector_retriever import VectorRetriever, EmbedderDummy, create_embedder
from core.soul_engine import SoulEngine
from core.action_router import ActionRouter
from core.blackboard import Blackboard
from core.task_system import TaskSystem
from core.code_agent import CodeAgent
from core.web_agent import WebAgent
from core.file_agent import FileAgent
from core.hitl_gateway import HITLGateway
from core.tool_executor import ToolExecutor
from core.core_memory_scheduler import CoreMemoryScheduler

from events.event_bus import EventBus, EVENT_BUS_CONFIG
from events.idempotent_writer import IdempotentWriter
from evolution.signal_extractor import SignalExtractor
from evolution.personality_evolver import PersonalityEvolver
from evolution.cognition_updater import CognitionUpdater
from evolution.evolution_journal import EvolutionJournal
from evolution.meta_cognition import MetaCognitionReflector
from evolution.observer import ObserverEngine

from services.graph_db import GraphDBClient, GraphDBClientDummy, Neo4jGraphDB
from services.vector_db import VectorDBClientDummy


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


class SnapshotStoreDummy:
    def __init__(self):
        self._snapshots: list = []

    async def save(self, snapshot) -> None:
        self._snapshots.append(snapshot)

    async def get_latest(self, block_type: str):
        matching = [s for s in self._snapshots if s.block_type == block_type]
        return matching[-1] if matching else None

    async def get_history(self, block_type: str, limit: int = 5) -> list:
        matching = [s for s in self._snapshots if s.block_type == block_type]
        return matching[-limit:]


class LLMInterfaceDummy:
    async def generate(self, prompt: str) -> str:
        return f"[LLM Mock Response to: {prompt[:50]}...]"

    async def generate_json(self, prompt: str) -> dict:
        return {"confidence": 0.6, "root_cause": "mock", "lesson": "mock"}


class AgentConfig:
    def __init__(
        self,
        llm: Optional[Any] = None,
        task_store: Optional[Any] = None,
        core_memory_store: Optional[Any] = None,
        journal_store: Optional[Any] = None,
        snapshot_store: Optional[Any] = None,
        graph_db: Optional[Any] = None,
        vector_db: Optional[Any] = None,
        redis_client: Optional[Any] = None,
        pg_pool: Optional[Any] = None,
        embedder: Optional[Any] = None,
        use_real_backends: bool = False,
    ):
        self.llm = llm or LLMInterfaceDummy()
        self.task_store = task_store or TaskStoreDummy()
        self.core_memory_store = core_memory_store or CoreMemoryStoreDummy()
        self.journal_store = journal_store or JournalStoreDummy()
        self.snapshot_store = snapshot_store or SnapshotStoreDummy()
        self.graph_db = graph_db or GraphDBClientDummy()
        self.vector_db = vector_db or VectorDBClientDummy()
        self.redis_client = redis_client
        self.pg_pool = pg_pool
        self.embedder = embedder or EmbedderDummy()
        self.use_real_backends = use_real_backends


class AgentApplication:
    def __init__(self, config: Optional[AgentConfig] = None):
        self._config = config or AgentConfig()
        self._running = False
        self._session_counter = 0

        self.llm = self._config.llm
        self.task_store = self._config.task_store
        self.core_memory_store = self._config.core_memory_store
        self.journal_store = self._config.journal_store
        self.snapshot_store = self._config.snapshot_store
        self.graph_db = self._config.graph_db
        self.vector_db = self._config.vector_db

        self.core_memory_cache: Optional[CoreMemoryCache] = None
        self.vector_retriever: Optional[VectorRetriever] = None
        self.event_bus: Optional[EventBus] = None
        self.blackboard: Optional[Blackboard] = None
        self.task_system: Optional[TaskSystem] = None
        self.code_agent: Optional[CodeAgent] = None
        self.web_agent: Optional[WebAgent] = None
        self.file_agent: Optional[FileAgent] = None
        self.core_memory_scheduler: Optional[CoreMemoryScheduler] = None
        self.soul_engine: Optional[SoulEngine] = None
        self.evolution_journal: Optional[EvolutionJournal] = None
        self.signal_extractor: Optional[SignalExtractor] = None
        self.personality_evolver: Optional[PersonalityEvolver] = None
        self.cognition_updater: Optional[CognitionUpdater] = None
        self.meta_cognition: Optional[MetaCognitionReflector] = None
        self.observer: Optional[ObserverEngine] = None
        self.hitl_gateway: Optional[HITLGateway] = None
        self.tool_executor: Optional[ToolExecutor] = None
        self.action_router: Optional[ActionRouter] = None
        self.idempotent_writer: Optional[IdempotentWriter] = None

    async def initialize(self) -> None:
        self.core_memory_cache = CoreMemoryCache()
        self.vector_retriever = VectorRetriever(
            embedder=self._config.embedder,
            vector_db=self.vector_db,
            redis_client=self._config.redis_client,
        )

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

        self.web_agent = WebAgent(
            task_store=self.task_store,
            blackboard=self.blackboard,
        )
        self.blackboard.register_agent(self.web_agent)

        self.file_agent = FileAgent(
            task_store=self.task_store,
            blackboard=self.blackboard,
        )
        self.blackboard.register_agent(self.file_agent)

        self.core_memory_scheduler = CoreMemoryScheduler(
            core_memory_store=self.core_memory_store,
            cache=self.core_memory_cache,
            llm=self.llm,
            snapshot_store=self.snapshot_store,
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

        self.meta_cognition = MetaCognitionReflector(
            llm_lite=self.llm,
            event_bus=self.event_bus,
        )

        self.observer = ObserverEngine(
            graph_db=self.graph_db,
            vector_db=self.vector_db,
            llm_lite=self.llm,
            event_bus=self.event_bus,
        )

        self.hitl_gateway = HITLGateway()
        self.tool_executor = ToolExecutor(
            core_memory_cache=self.core_memory_cache,
            llm=self.llm,
            event_bus=self.event_bus,
        )

        self.action_router = ActionRouter(
            task_system=self.task_system,
            blackboard=self.blackboard,
            hitl_gateway=self.hitl_gateway,
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
        )

        self.idempotent_writer = IdempotentWriter(
            redis_client=self._config.redis_client,
        )
        await self.idempotent_writer.start()

        await self._setup_event_subscriptions()
        await self.event_bus.start()
        await self.task_system.start()

        asyncio.create_task(self._task_worker_loop())
        asyncio.create_task(self._slow_evolution_loop())

        await self._load_core_memory()

        self._running = True
        print("[AgentApplication] 初始化完成")

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
            await self.meta_cognition.reflect(task)

        async def handle_task_failed(event: Event) -> None:
            task_data = event.payload.get("task")
            if not task_data:
                return

            from domain.task import Task

            task = Task(**task_data)
            await self.meta_cognition.reflect(task)

        async def handle_lesson_generated(event: Event) -> None:
            lesson_data = event.payload.get("lesson")
            user_id = event.payload.get("user_id", "default")

            if not lesson_data:
                return

            lesson = Lesson(**lesson_data)
            await self.cognition_updater.update(lesson, user_id)

            signals = self._collect_pending_signals(user_id)
            if lesson.is_pattern and signals:
                await self.personality_evolver.slow_evolve(signals, user_id)

        async def handle_observation_done(event: Event) -> None:
            session_id = event.payload.get("session_id", "")
            triplet_count = event.payload.get("triplet_count", 0)
            print(
                f"[AgentApplication] Observation done: session={session_id}, triplets={triplet_count}"
            )

        await self.event_bus.subscribe("dialogue_ended", handle_dialogue_ended)
        await self.event_bus.subscribe("task_completed", handle_task_completed)
        await self.event_bus.subscribe("task_failed", handle_task_failed)
        await self.event_bus.subscribe("lesson_generated", handle_lesson_generated)
        await self.event_bus.subscribe("observation_done", handle_observation_done)

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
        print("[AgentApplication] slow_evolution_loop started")
        while self._running:
            await asyncio.sleep(SLOW_EVOLVE_INTERVAL)
            self._session_counter += 1
            if self._session_counter >= SLOW_EVOLVE_SESSION_THRESHOLD:
                self._session_counter = 0
                user_ids = await self._get_active_users()
                for user_id in user_ids:
                    signals = self._collect_pending_signals(user_id)
                    await self.personality_evolver.slow_evolve(signals, user_id)
                    print(
                        f"[AgentApplication] slow_evolve completed for user: {user_id}"
                    )
        print("[AgentApplication] slow_evolution_loop stopped")

    async def run(self) -> None:
        print("[AgentApplication] 运行中...")
        while self._running:
            await asyncio.sleep(1)

    async def shutdown(self) -> None:
        self._running = False
        if self.idempotent_writer:
            await self.idempotent_writer.stop()
        await self.task_system.stop()
        await self.event_bus.stop()
        print("[AgentApplication] 已关闭")

    async def chat(self, user_id: str, session_id: str, message: str) -> dict:
        prompt = await self.soul_engine.build_prompt(
            user_id,
            session_id,
            message,
        )

        result = await self.soul_engine.think(prompt)

        action_result = await self.action_router.route(
            result,
            {"user_id": user_id, "session_id": session_id},
        )

        await self.event_bus.emit(
            "dialogue_ended",
            {
                "user_id": user_id,
                "session_id": session_id,
                "dialogue": [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": action_result.get("content", "")},
                ],
            },
        )

        return {
            "reply": action_result.get("content", ""),
            "action": action_result.get("action", "direct_reply"),
            "task_id": action_result.get("task_id"),
            "inner_thoughts": result.get("inner_thoughts"),
        }


async def create_production_config() -> AgentConfig:
    from services.llm import create_llm

    import redis.asyncio as aioredis
    import asyncpg

    llm = create_llm()

    redis_url = os.getenv("REDIS_URL", "").strip()
    redis_client = None
    task_store = TaskStoreDummy()
    core_memory_store = CoreMemoryStoreDummy()

    if redis_url:
        try:
            redis_client = aioredis.from_url(redis_url)
            await redis_client.ping()

            from services.task_store_redis import RedisTaskStore
            from services.core_memory_store_redis import RedisCoreMemoryStore

            task_store = RedisTaskStore(redis_client)
            core_memory_store = RedisCoreMemoryStore(redis_client)
            print(f"[AgentConfig] Redis: connected ({redis_url})")
        except Exception as e:
            print(f"[AgentConfig] Redis 连接失败，使用 Dummy: {e}")
            redis_client = None
    else:
        print("[AgentConfig] Redis: Dummy (set REDIS_URL 启用真实 Redis)")

    pg_url = os.getenv("POSTGRES_URL", "").strip()
    pg_pool = None
    journal_store = JournalStoreDummy()
    snapshot_store = SnapshotStoreDummy()

    if pg_url:
        try:
            pg_pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=5)

            from services.journal_store_postgres import PostgresJournalStore
            from services.snapshot_store_postgres import PostgresSnapshotStore

            journal_store = PostgresJournalStore(pg_pool)
            await journal_store.initialize()
            snapshot_store = PostgresSnapshotStore(pg_pool)
            await snapshot_store.initialize()
            print(f"[AgentConfig] PostgreSQL: connected ({pg_url})")
        except Exception as e:
            print(f"[AgentConfig] PostgreSQL 连接失败，使用 Dummy: {e}")
            if pg_pool:
                await pg_pool.close()
                pg_pool = None
    else:
        print("[AgentConfig] PostgreSQL: Dummy (set POSTGRES_URL 启用真实 PostgreSQL)")

    neo4j_uri = os.getenv("NEO4J_URI", "").strip()
    neo4j_user = os.getenv("NEO4J_USER", "").strip()
    neo4j_password = os.getenv("NEO4J_PASSWORD", "").strip()
    graph_db: Any = GraphDBClientDummy()

    if neo4j_uri and neo4j_user and neo4j_password:
        try:
            graph_db = GraphDBClient(
                db_impl=Neo4jGraphDB(
                    uri=neo4j_uri, user=neo4j_user, password=neo4j_password
                )
            )
            print(f"[AgentConfig] Neo4j: connected ({neo4j_uri})")
        except Exception as e:
            print(f"[AgentConfig] Neo4j 连接失败，使用 Dummy: {e}")
            graph_db = GraphDBClientDummy()
    else:
        print(
            "[AgentConfig] Neo4j: Dummy (set NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD 启用真实 Neo4j)"
        )

    embedder = create_embedder()

    return AgentConfig(
        llm=llm,
        task_store=task_store,
        core_memory_store=core_memory_store,
        journal_store=journal_store,
        snapshot_store=snapshot_store,
        graph_db=graph_db,
        redis_client=redis_client,
        pg_pool=pg_pool,
        embedder=embedder,
        use_real_backends=True,
    )
