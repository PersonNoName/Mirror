import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from contextlib import asynccontextmanager

import fakeredis.aioredis

from domain.task import Task
from domain.memory import (
    CoreMemory,
)
from domain.evolution import EvolutionEntry

from services.task_store_redis import RedisTaskStore
from services.core_memory_store_redis import RedisCoreMemoryStore
from services.journal_store_postgres import PostgresJournalStore
from services.llm import LLMInterface


class FakePool:
    def __init__(self):
        self._conn = FakeConnection()
        self._initialized = False

    async def initialize(self):
        self._initialized = True

    @asynccontextmanager
    async def acquire(self):
        yield self._conn

    async def close(self):
        pass


class FakeConnection:
    def __init__(self):
        self._inserted = []

    async def execute(self, query, *args):
        if "CREATE TABLE" in query:
            return
        if "INSERT INTO" in query:
            self._inserted.append(args)
            return 1
        return 0

    async def fetch(self, query, *args):
        if "ORDER BY timestamp DESC" in query:
            result = list(reversed(self._inserted))
            return [
                dict(
                    zip(
                        ["id", "timestamp", "type", "summary", "detail", "session_id"],
                        row,
                    )
                )
                for row in result
            ]
        if "WHERE session_id" in query:
            return [
                dict(
                    zip(
                        ["id", "timestamp", "type", "summary", "detail", "session_id"],
                        row,
                    )
                )
                for row in self._inserted
                if len(row) > 5 and row[5] == args[0]
            ]
        return [
            dict(
                zip(["id", "timestamp", "type", "summary", "detail", "session_id"], row)
            )
            for row in self._inserted
        ]

    async def fetchrow(self, query, *args):
        rows = await self.fetch(query, *args)
        return rows[0] if rows else None


class FakeResponse:
    def __init__(self, text: str):
        self.choices = [FakeChoice(text)]


class FakeChoice:
    def __init__(self, text: str):
        self.message = type("Msg", (), {"content": text})()


class FakeChat:
    def __init__(self, response_text: str):
        self._response_text = response_text

    @property
    def completions(self):
        return FakeCompletions(self._response_text)


class FakeCompletions:
    def __init__(self, text: str):
        self._text = text

    async def create(self, **kwargs):
        return FakeResponse(self._text)


class FakeAsyncOpenAI:
    def __init__(self, *, api_key: str = ""):
        self.api_key = api_key
        self._response_text = '{"result": "ok"}'

    @property
    def chat(self):
        return FakeChat(self._response_text)

    def set_response(self, text: str):
        self._response_text = text


def make_fake_openai(response_text: str = '{"result": "ok"}'):
    return FakeAsyncOpenAI(api_key="test")


async def test_task_store_redis():
    print("\n=== Test: RedisTaskStore ===")
    redis_client = fakeredis.aioredis.FakeRedis()
    store = RedisTaskStore(redis_client)

    task = Task(intent="Test task", priority=1, status="pending")
    created = await store.create(task)
    assert created.id == task.id

    retrieved = await store.get(task.id)
    assert retrieved is not None
    assert retrieved.intent == "Test task"

    retrieved.status = "running"
    await store.update(retrieved)

    heartbeat_updated = await store.get(task.id)
    assert heartbeat_updated.last_heartbeat_at == retrieved.last_heartbeat_at

    by_status = await store.get_by_status("pending")
    task_ids = [t.id for t in by_status]
    assert task.id in task_ids, f"Task {task.id} not found in {task_ids}"

    print("  [PASS] RedisTaskStore CRUD and indexing works")
    await redis_client.aclose()


async def test_task_store_redis_parent():
    print("\n=== Test: RedisTaskStore parent indexing ===")
    redis_client = fakeredis.aioredis.FakeRedis()
    store = RedisTaskStore(redis_client)

    parent = Task(intent="Parent task")
    await store.create(parent)

    child = Task(intent="Child task", parent_task_id=parent.id)
    await store.create(child)

    children = await store.get_by_parent(parent.id)
    assert len(children) == 1
    assert children[0].id == child.id

    print("  [PASS] RedisTaskStore parent indexing works")
    await redis_client.aclose()


async def test_core_memory_store_cas():
    print("\n=== Test: RedisCoreMemoryStore CAS ===")
    redis_client = fakeredis.aioredis.FakeRedis()

    async def mock_eval(lua, num_keys, *args):
        key = args[0]
        expected_version = int(args[1])
        new_data = args[2]

        current_version_str = await redis_client.hget(key, "version")
        current_version = int(current_version_str) if current_version_str else 0

        if current_version != expected_version:
            return 0

        pipe = redis_client.pipeline()
        pipe.hset(key, "data", new_data)
        pipe.hincrby(key, "version", 1)
        await pipe.execute()
        return 1

    redis_client.eval = mock_eval

    store = RedisCoreMemoryStore(redis_client)

    key = "user1:self_cognition"
    value = {"test": "data1"}

    ok = await store.cas_upsert(key, value, expected_version=0)
    assert ok is True

    ok2 = await store.cas_upsert(key, {"test": "data2"}, expected_version=0)
    assert ok2 is False

    ok3 = await store.cas_upsert(key, {"test": "data3"}, expected_version=1)
    assert ok3 is True

    print("  [PASS] RedisCoreMemoryStore CAS works")
    await redis_client.aclose()


async def test_core_memory_store_force():
    print("\n=== Test: RedisCoreMemoryStore force_upsert ===")
    redis_client = fakeredis.aioredis.FakeRedis()
    store = RedisCoreMemoryStore(redis_client)

    key = "user1:world_model"
    await store.force_upsert(key, {"env_constraints": ["no harm"]})
    await store.force_upsert(key, {"env_constraints": ["obey user"]})

    data, version = await store.get_with_version(key)
    assert version == 2
    assert data["env_constraints"] == ["obey user"]

    print("  [PASS] RedisCoreMemoryStore force_upsert works")
    await redis_client.aclose()


async def test_core_memory_store_get_core_memory():
    print("\n=== Test: RedisCoreMemoryStore get_core_memory ===")
    redis_client = fakeredis.aioredis.FakeRedis()
    store = RedisCoreMemoryStore(redis_client)

    await store.force_upsert(
        "user1:self_cognition",
        {
            "capability_map": {},
            "known_limits": [],
            "mission_clarity": [],
            "blindspots": [],
            "version": 1,
        },
    )
    await store.force_upsert(
        "user1:world_model",
        {
            "env_constraints": ["constraint1"],
            "user_model": {},
            "agent_profiles": {},
            "social_rules": [],
        },
    )

    mem = await store.get_core_memory("user1")
    assert isinstance(mem, CoreMemory)
    assert mem.self_cognition is not None
    assert mem.world_model.env_constraints == ["constraint1"]

    print("  [PASS] RedisCoreMemoryStore get_core_memory works")
    await redis_client.aclose()


async def test_postgres_journal_store():
    print("\n=== Test: PostgresJournalStore ===")
    pool = FakePool()
    store = PostgresJournalStore(pool)

    await store.initialize()

    entry = EvolutionEntry(
        type="fast_adaptation",
        summary="Test adaptation",
        detail={"signal": "test"},
        session_id="session1",
    )

    await store.append(entry)

    recent = await store.get_recent(10)
    assert len(recent) == 1, f"Expected 1 entry, got {len(recent)}"
    assert recent[0].summary == "Test adaptation"

    by_session = await store.get_by_session("session1")
    assert len(by_session) == 1

    print("  [PASS] PostgresJournalStore append/query works")
    await pool.close()


async def test_llm_interface_generate():
    print("\n=== Test: LLMInterface generate ===")

    expected_text = "Hello from mock"

    class MockAsyncOpenAI:
        def __init__(self, *, api_key: str = "", base_url: str | None = None):
            self.api_key = api_key
            self.base_url = base_url

        @property
        def chat(self):
            return FakeChat(expected_text)

    import services.llm as llm_module

    original = llm_module.AsyncOpenAI
    llm_module.AsyncOpenAI = MockAsyncOpenAI

    try:
        interface = LLMInterface(api_key="test-key", model="gpt-4")
        result = await interface.generate("Say hello")
        assert result == expected_text
        print("  [PASS] LLMInterface generate works")
    finally:
        llm_module.AsyncOpenAI = original


async def test_llm_interface_generate_json():
    print("\n=== Test: LLMInterface generate_json ===")

    expected = {"confidence": 0.9, "root_cause": "test"}

    class MockAsyncOpenAI:
        def __init__(self, *, api_key: str = "", base_url: str | None = None):
            self.api_key = api_key
            self.base_url = base_url

        @property
        def chat(self):
            return FakeChat(json.dumps(expected))

    import services.llm as llm_module

    original = llm_module.AsyncOpenAI
    llm_module.AsyncOpenAI = MockAsyncOpenAI

    try:
        interface = LLMInterface(api_key="test-key", model="gpt-4")
        result = await interface.generate_json("Return JSON")
        assert result == expected
        print("  [PASS] LLMInterface generate_json works")
    finally:
        llm_module.AsyncOpenAI = original


async def main():
    print("=" * 60)
    print("Service Layer Tests")
    print("=" * 60)

    tests = [
        test_task_store_redis,
        test_task_store_redis_parent,
        test_core_memory_store_cas,
        test_core_memory_store_force,
        test_core_memory_store_get_core_memory,
        test_postgres_journal_store,
        test_llm_interface_generate,
        test_llm_interface_generate_json,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {test.__name__}: {e}")
            import traceback

            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
