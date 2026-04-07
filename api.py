import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

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

from services.graph_db import GraphDBClient, GraphDBClientDummy
from services.vector_db import VectorDBClientDummy

from services.llm import LLMInterface
from services.task_store_redis import RedisTaskStore
from services.core_memory_store_redis import RedisCoreMemoryStore
from services.journal_store_postgres import PostgresJournalStore
from services.snapshot_store_postgres import PostgresSnapshotStore

import redis.asyncio as aioredis
import asyncpg

load_dotenv()


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    action: str
    task_id: Optional[str] = None
    inner_thoughts: Optional[str] = None


class LLMInterfaceDummy:
    async def generate(self, prompt: str) -> str:
        return f"[LLM Mock Response to: {prompt[:50]}...]"

    async def generate_json(self, prompt: str) -> dict:
        return {"confidence": 0.6, "root_cause": "mock", "lesson": "mock"}


class JournalStoreDummy:
    def __init__(self):
        self._entries: list = []

    async def append(self, entry) -> None:
        self._entries.append(entry)

    async def get_recent(self, last_n: int) -> list:
        return self._entries[-last_n:] if self._entries else []

    async def get_by_session(self, session_id: str) -> list:
        return [e for e in self._entries if e.session_id == session_id]


class TaskStoreDummy:
    def __init__(self):
        self._tasks: dict = {}
        self._user_ids: list = []

    async def create(self, task):
        self._tasks[task.id] = task
        return task

    async def get(self, task_id: str):
        return self._tasks.get(task_id)

    async def update(self, task) -> None:
        self._tasks[task.id] = task

    async def update_heartbeat(self, task_id: str, timestamp) -> None:
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
        self._data: dict = {}

    async def get_with_version(self, key: str) -> tuple:
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

    async def get_core_memory(self, user_id: str):
        from domain.memory import CoreMemory

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


class AgentState:
    def __init__(self):
        self.llm = LLMInterfaceDummy()
        self.task_store = TaskStoreDummy()
        self.core_memory_store = CoreMemoryStoreDummy()
        self.journal_store = JournalStoreDummy()
        self.snapshot_store = SnapshotStoreDummy()
        self.graph_db: GraphDBClientDummy = GraphDBClientDummy()
        self.vector_db = VectorDBClientDummy()

        self.core_memory_cache: CoreMemoryCache = CoreMemoryCache()
        self.vector_retriever: VectorRetriever = VectorRetriever(
            embedder=EmbedderDummy(),
            vector_db=self.vector_db,
        )
        self.event_bus: EventBus = EventBus(EVENT_BUS_CONFIG)
        self.blackboard: Blackboard = Blackboard(
            task_store=self.task_store,
            event_bus=self.event_bus,
            agent_registry={},
        )
        self.task_system: TaskSystem = TaskSystem(
            task_store=self.task_store,
            blackboard=self.blackboard,
        )
        self.code_agent: CodeAgent = CodeAgent(
            task_store=self.task_store,
            blackboard=self.blackboard,
            core_memory_cache=self.core_memory_cache,
        )
        self.blackboard.register_agent(self.code_agent)

        self.core_memory_scheduler: CoreMemoryScheduler = CoreMemoryScheduler(
            core_memory_store=self.core_memory_store,
            cache=self.core_memory_cache,
            llm=self.llm,
        )
        self.soul_engine: SoulEngine = SoulEngine(
            core_memory_cache=self.core_memory_cache,
            vector_retriever=self.vector_retriever,
            llm=self.llm,
        )
        self.evolution_journal: EvolutionJournal = EvolutionJournal(
            journal_store=self.journal_store,
            llm_lite=self.llm,
        )
        self.signal_extractor: SignalExtractor = SignalExtractor()
        self.personality_evolver: PersonalityEvolver = PersonalityEvolver(
            core_memory_cache=self.core_memory_cache,
            llm_lite=self.llm,
            evolution_journal=self.evolution_journal,
            graph_db=self.graph_db,
            core_memory_scheduler=self.core_memory_scheduler,
        )
        self.cognition_updater: CognitionUpdater = CognitionUpdater(
            core_memory_cache=self.core_memory_cache,
            graph_db=self.graph_db,
            core_memory_scheduler=self.core_memory_scheduler,
        )
        self.meta_cognition: MetaCognitionReflector = MetaCognitionReflector(
            llm_lite=self.llm
        )
        self.observer: ObserverEngine = ObserverEngine(
            graph_db=self.graph_db,
            vector_db=self.vector_db,
            llm_lite=self.llm,
        )
        self.action_router: ActionRouter = ActionRouter(
            task_system=self.task_system,
            blackboard=self.blackboard,
            hitl_gateway=HITLGatewayDummy(),
            tool_executor=ToolExecutorDummy(),
            event_bus=self.event_bus,
        )

        self._running = False
        self._session_counter = 0
        self._redis_client = None
        self._pg_pool = None

    async def initialize(self) -> None:
        await self._try_connect_backends()
        await self.event_bus.start()
        await self.task_system.start()
        asyncio.create_task(self._task_worker_loop())
        await self._load_core_memory()
        asyncio.create_task(self._slow_evolution_loop())
        self._running = True
        print("[AgentState] 初始化完成")

    async def _try_connect_backends(self) -> None:
        print("[AgentState] 检测后端配置...")
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        if openai_key:
            llm_base_url = os.getenv("LLM_BASE_URL", "").strip() or None
            llm_model = os.getenv("LLM_MODEL", "").strip() or "gpt-4"
            self.llm = LLMInterface(
                api_key=openai_key,
                base_url=llm_base_url,
                model=llm_model,
            )
            self.core_memory_scheduler = CoreMemoryScheduler(
                core_memory_store=self.core_memory_store,
                cache=self.core_memory_cache,
                llm=self.llm,
            )
            self.personality_evolver = PersonalityEvolver(
                core_memory_cache=self.core_memory_cache,
                llm_lite=self.llm,
                evolution_journal=self.evolution_journal,
                graph_db=self.graph_db,
                core_memory_scheduler=self.core_memory_scheduler,
            )
            print(
                f"[AgentState] LLM: real ({llm_base_url or 'OpenAI compat'}, model={llm_model})"
            )
        else:
            print("[AgentState] LLM: Dummy (set OPENAI_API_KEY 启用真实 LLM)")

        redis_url = os.getenv("REDIS_URL", "").strip()
        if redis_url:
            try:
                self._redis_client = aioredis.from_url(redis_url)
                await self._redis_client.ping()
                self.task_store = RedisTaskStore(self._redis_client)
                self.core_memory_store = RedisCoreMemoryStore(self._redis_client)
                print(f"[AgentState] Redis: connected ({redis_url})")
            except Exception as e:
                print(f"[AgentState] Redis 连接失败，使用 Dummy: {e}")
                self._redis_client = None
        else:
            print("[AgentState] Redis: Dummy (set REDIS_URL 启用真实 Redis)")

        pg_url = os.getenv("POSTGRES_URL", "").strip()
        if pg_url:
            try:
                self._pg_pool = await asyncpg.create_pool(
                    pg_url, min_size=1, max_size=5
                )
                self.journal_store = PostgresJournalStore(self._pg_pool)
                await self.journal_store.initialize()
                self.snapshot_store = PostgresSnapshotStore(self._pg_pool)
                await self.snapshot_store.initialize()
                print(f"[AgentState] PostgreSQL: connected ({pg_url})")
            except Exception as e:
                print(f"[AgentState] PostgreSQL 连接失败，使用 Dummy: {e}")
                if self._pg_pool:
                    await self._pg_pool.close()
                    self._pg_pool = None
        else:
            print(
                "[AgentState] PostgreSQL: Dummy (set POSTGRES_URL 启用真实 PostgreSQL)"
            )

        neo4j_uri = os.getenv("NEO4J_URI", "").strip()
        neo4j_user = os.getenv("NEO4J_USER", "").strip()
        neo4j_password = os.getenv("NEO4J_PASSWORD", "").strip()
        if neo4j_uri and neo4j_user and neo4j_password:
            try:
                self.graph_db = GraphDBClient(
                    uri=neo4j_uri, user=neo4j_user, password=neo4j_password
                )
                print(f"[AgentState] Neo4j: connected ({neo4j_uri})")
            except Exception as e:
                print(f"[AgentState] Neo4j 连接失败，使用 Dummy: {e}")
                self.graph_db = GraphDBClientDummy()
        else:
            print(
                "[AgentState] Neo4j: Dummy (set NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD 启用真实 Neo4j)"
            )

    async def _task_worker_loop(self) -> None:
        print("[AgentState] task_worker_loop started")
        while self._running:
            task = await self.task_system.queue.dequeue()
            if task:
                await self.blackboard.assign(task)
            else:
                await asyncio.sleep(0.1)
        print("[AgentState] task_worker_loop stopped")

    async def _slow_evolution_loop(self) -> None:
        SLOW_EVOLVE_INTERVAL = 3600
        SLOW_EVOLVE_SESSION_THRESHOLD = 10
        print("[AgentState] slow_evolution_loop started")
        while self._running:
            await asyncio.sleep(SLOW_EVOLVE_INTERVAL)
            self._session_counter += 1
            if self._session_counter >= SLOW_EVOLVE_SESSION_THRESHOLD:
                self._session_counter = 0
                user_ids = await self._get_active_users()
                for user_id in user_ids:
                    signals = self._collect_pending_signals(user_id)
                    await self.personality_evolver.slow_evolve(signals, user_id)
                    print(f"[AgentState] slow_evolve completed for user: {user_id}")
        print("[AgentState] slow_evolution_loop stopped")

    async def _get_active_users(self) -> list[str]:
        if hasattr(self.task_store, "get_all_user_ids"):
            return await self.task_store.get_all_user_ids()
        return []

    def _collect_pending_signals(self, user_id: str) -> list:
        return []

    async def _load_core_memory(self) -> None:
        user_ids = await self._get_active_users()
        if not user_ids:
            print("[AgentState] No user IDs found, skipping core memory load")
            return
        for user_id in user_ids:
            memory = await self.core_memory_store.get_core_memory(user_id)
            self.core_memory_cache.set(user_id, memory)
            print(f"[AgentState] Loaded core memory for user: {user_id}")

    async def shutdown(self) -> None:
        self._running = False
        await self.task_system.stop()
        await self.event_bus.stop()
        if self._redis_client:
            await self._redis_client.close()
        if self._pg_pool:
            await self._pg_pool.close()
        print("[AgentState] 已关闭")


_state: AgentState | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _state
    _state = AgentState()
    await _state.initialize()
    yield
    if _state:
        await _state.shutdown()


app = FastAPI(title="Mirror Agent API", lifespan=lifespan)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if _state is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    prompt = await _state.soul_engine.build_prompt(
        request.user_id,
        request.session_id,
        request.message,
    )

    result = await _state.soul_engine.think(prompt)

    action_result = await _state.action_router.route(
        result,
        {"user_id": request.user_id, "session_id": request.session_id},
    )

    await _state.event_bus.emit(
        "dialogue_ended",
        {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "dialogue": [
                {"role": "user", "content": request.message},
                {"role": "assistant", "content": action_result.get("content", "")},
            ],
        },
    )

    return ChatResponse(
        reply=action_result.get("content", ""),
        action=action_result.get("action", "direct_reply"),
        task_id=action_result.get("task_id"),
        inner_thoughts=result.get("inner_thoughts"),
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
