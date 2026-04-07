import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from datetime import datetime

from domain.task import Task, TaskStatus
from domain.memory import CoreMemory, PersonalityState, BehavioralRule
from domain.evolution import InteractionSignal, Lesson

from core.memory_cache import CoreMemoryCache
from core.soul_engine import SoulEngine, TOKEN_BUDGET_CONFIG
from core.blackboard import Blackboard
from core.code_agent import CodeAgent

from events.event_bus import EventBus, EVENT_BUS_CONFIG
from evolution.signal_extractor import SignalExtractor
from evolution.personality_evolver import PersonalityEvolver
from evolution.cognition_updater import CognitionUpdater
from evolution.evolution_journal import EvolutionJournal
from evolution.meta_cognition import MetaCognitionReflector

from services.graph_db import GraphDBClient
from services.vector_db import VectorDBClient
from core.core_memory_scheduler import CoreMemoryScheduler


class DummyTaskStore:
    def __init__(self):
        self._tasks = {}

    async def create(self, task):
        self._tasks[task.id] = task
        return task

    async def get(self, task_id):
        return self._tasks.get(task_id)

    async def update(self, task):
        self._tasks[task.id] = task

    async def update_heartbeat(self, task_id, timestamp):
        if task_id in self._tasks:
            self._tasks[task_id].last_heartbeat_at = timestamp

    async def get_by_status(self, status):
        return [t for t in self._tasks.values() if t.status == status]


class DummyCoreMemoryStore:
    def __init__(self):
        self._data = {}

    async def get_with_version(self, key):
        if key in self._data:
            return self._data[key]
        return {}, 0

    async def cas_upsert(self, key, value, expected_version):
        if key in self._data:
            _, version = self._data[key]
            if version != expected_version:
                return False
        self._data[key] = (value, expected_version + 1)
        return True

    async def force_upsert(self, key, value):
        current = self._data.get(key, ({}, 0))
        self._data[key] = (value, current[1] + 1)


class DummyJournalStore:
    def __init__(self):
        self._entries = []

    async def append(self, entry):
        self._entries.append(entry)
        print(f"  [Journal] Recorded: {entry.type} - {entry.summary[:50]}")

    async def get_recent(self, last_n):
        return self._entries[-last_n:] if self._entries else []


class DummyLLM:
    async def generate(self, prompt):
        print(f"  [LLM] Generating response...")
        await asyncio.sleep(0.1)
        return f"[Mock LLM response to: {prompt[:80]}...]"


class DummyEventBus:
    def __init__(self):
        self._handlers = {}

    async def emit(self, event_type, payload):
        print(f"  [EventBus] emit: {event_type}")
        handlers = self._handlers.get(event_type, [])
        for handler in handlers:
            await handler(type=event_type, payload=payload)

    async def subscribe(self, event_type, handler):
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)


async def test_memory_cache():
    print("\n=== Test 1: CoreMemoryCache (per-user) ===")
    cache = CoreMemoryCache()

    cache.set(
        "user1",
        CoreMemory(
            personality=PersonalityState(
                baseline_description="Test personality for user1"
            )
        ),
    )
    cache.set(
        "user2",
        CoreMemory(
            personality=PersonalityState(
                baseline_description="Test personality for user2"
            )
        ),
    )

    u1_mem = cache.get("user1")
    u2_mem = cache.get("user2")

    assert u1_mem.personality.baseline_description == "Test personality for user1"
    assert u2_mem.personality.baseline_description == "Test personality for user2"
    print("  [PASS] per-user isolation works correctly")
    return True


async def test_soul_engine():
    print("\n=== Test 2: SoulEngine Prompt Building ===")
    cache = CoreMemoryCache()
    cache.set(
        "test_user",
        CoreMemory(
            personality=PersonalityState(
                behavioral_rules=[
                    BehavioralRule(content="回复要简洁", source="test", confidence=0.9),
                    BehavioralRule(
                        content="使用技术术语", source="test", confidence=0.8
                    ),
                ],
                session_adaptations=["本次对话请用英文回复"],
            )
        ),
    )

    engine = SoulEngine(core_memory_cache=cache, vector_retriever=None)

    prompt = await engine.build_prompt(
        user_id="test_user", session_id="session123", user_message="Hello, how are you?"
    )

    assert "回复要简洁" in prompt
    assert "使用技术术语" in prompt
    assert "本次对话请用英文回复" in prompt
    assert "traits_internal" not in prompt
    print(
        "  [PASS] Prompt built correctly with behavioral rules and session adaptations"
    )
    print(f"  Prompt length: {len(prompt)} chars")
    return True


async def test_event_bus():
    print("\n=== Test 3: EventBus ===")
    bus = EventBus(EVENT_BUS_CONFIG)
    await bus.start()

    events_received = []

    async def handler1(event):
        events_received.append(("handler1", event.type))

    async def handler2(event):
        events_received.append(("handler2", event.type))

    await bus.subscribe("test_event", handler1)
    await bus.subscribe("test_event", handler2)

    await bus.emit("test_event", {"data": "test"})
    await asyncio.sleep(0.1)

    assert len(events_received) == 2
    print(f"  [PASS] Both handlers received the event: {events_received}")

    await bus.stop()
    return True


async def test_signal_extractor():
    print("\n=== Test 4: SignalExtractor ===")
    extractor = SignalExtractor()

    dialogue = [
        {"role": "user", "content": "你好，请简洁回复"},
        {"role": "assistant", "content": "好的，我会简洁回复。"},
        {"role": "user", "content": "不对，我说的是用英文回复"},
        {"role": "assistant", "content": "Sorry, I will reply in English."},
        {"role": "user", "content": "好的"},
    ]

    signals = await extractor.extract(dialogue, "session123", turn_index=5)

    print(f"  Extracted {len(signals)} signals:")
    for s in signals:
        print(f"    - type={s.type}, tag={s.behavior_tag}, content={s.content[:30]}")

    assert len(signals) >= 1
    print("  [PASS] Signal extraction works")
    return True


async def test_personality_evolver():
    print("\n=== Test 5: PersonalityEvolver (双速进化) ===")
    cache = CoreMemoryCache()
    cache.set("test_user", CoreMemory())

    journal = EvolutionJournal(journal_store=DummyJournalStore(), llm_lite=DummyLLM())
    evolver = PersonalityEvolver(
        core_memory_cache=cache,
        llm_lite=DummyLLM(),
        evolution_journal=journal,
    )

    signal = InteractionSignal(
        type="explicit_instruction",
        content="请用更简洁的方式回复",
        behavior_tag="shorten_response",
        strength=1.0,
        session_id="session123",
        turn_index=1,
    )

    adaptation = await evolver.fast_adapt(signal, "test_user")
    print(f"  Fast adaptation result: {adaptation}")

    u1_mem = cache.get("test_user")
    assert len(u1_mem.personality.session_adaptations) >= 1
    print("  [PASS] Fast adapt works, session_adaptations updated")
    return True


async def test_blackboard():
    print("\n=== Test 6: Blackboard (无状态) ===")
    task_store = DummyTaskStore()
    event_bus = DummyEventBus()
    blackboard = Blackboard(task_store=task_store, event_bus=event_bus)

    class DummyAgent:
        name = "test_agent"
        domain = "test"

        async def execute(self, task):
            print(f"    Agent executing task: {task.id}")
            await asyncio.sleep(0.1)

        async def estimate_capability(self, task):
            return 0.8

    blackboard.register_agent(DummyAgent())

    task = Task(intent="Test task", priority=1)
    task = await task_store.create(task)

    agent, score = await blackboard.evaluate_agents(task)
    print(f"  Evaluated agent: {agent.name}, score: {score}")
    assert agent.name == "test_agent"
    assert score == 0.8

    print("  [PASS] Blackboard agent evaluation works")
    return True


async def test_task_system():
    print("\n=== Test 7: TaskSystem (优先级队列) ===")
    task_store = DummyTaskStore()
    event_bus = DummyEventBus()
    blackboard = Blackboard(task_store=task_store, event_bus=event_bus)

    from core.task_system import TaskSystem

    task_system = TaskSystem(task_store=task_store, blackboard=blackboard)

    t1 = await task_system.create_task({"intent": "Low priority", "priority": 2})
    t2 = await task_system.create_task({"intent": "High priority", "priority": 0})
    t3 = await task_system.create_task({"intent": "Normal priority", "priority": 1})

    print(f"  Created 3 tasks with priorities 2, 0, 1")
    print(f"  Pending count: {task_system.queue.get_pending_count()}")

    dequeued = await task_system.queue.dequeue()
    print(f"  First dequeued: priority={dequeued.priority}, intent={dequeued.intent}")
    assert dequeued.priority == 0

    print("  [PASS] Priority queue works (0=urgent first)")
    return True


async def test_cognition_updater():
    print("\n=== Test 8: CognitionUpdater (分发) ===")
    cache = CoreMemoryCache()
    cache.set("test_user", CoreMemory())

    updater = CognitionUpdater(
        core_memory_cache=cache,
        graph_db=GraphDBClient(),
        core_memory_scheduler=None,
    )

    lesson1 = Lesson(
        task_id="task1",
        domain="code",
        outcome="done",
        root_cause="success",
        lesson_text="Learned to handle this case",
        is_agent_capability_issue=True,
    )

    await updater.update(lesson1, "test_user")

    u1_mem = cache.get("test_user")
    print(f"  SelfCognition capability_map: {u1_mem.self_cognition.capability_map}")
    assert "code" in u1_mem.self_cognition.capability_map

    print("  [PASS] CognitionUpdater分发正确")
    return True


async def test_core_memory_scheduler():
    print("\n=== Test 9: CoreMemoryScheduler (CAS + 预算) ===")
    cache = CoreMemoryCache()
    cache.set("test_user", CoreMemory())

    store = DummyCoreMemoryStore()
    scheduler = CoreMemoryScheduler(
        core_memory_store=store,
        cache=cache,
    )

    await scheduler.write("self_cognition", {"test": "data1"})

    current, version = await store.get_with_version("core_memory:self_cognition")
    print(f"  Written data version: {version}")
    assert version == 1

    print("  [PASS] CoreMemoryScheduler CAS write works")
    return True


async def test_integration_flow():
    print("\n=== Test 10: Integration Flow ===")
    print("  Simulating: dialogue_ended -> SignalExtractor -> PersonalityEvolver")

    cache = CoreMemoryCache()
    cache.set("user123", CoreMemory())

    journal = EvolutionJournal(journal_store=DummyJournalStore(), llm_lite=DummyLLM())
    extractor = SignalExtractor()
    evolver = PersonalityEvolver(
        core_memory_cache=cache,
        llm_lite=DummyLLM(),
        evolution_journal=journal,
    )

    dialogue = [
        {"role": "user", "content": "请更简洁一些"},
        {"role": "assistant", "content": "好的，我会简洁回复。"},
    ]

    signals = await extractor.extract(dialogue, "session456", turn_index=2)
    for sig in signals:
        print(f"  Signal: {sig.type} - {sig.behavior_tag}")
        await evolver.fast_adapt(sig, "user123")

    final_mem = cache.get("user123")
    print(f"  Session adaptations: {final_mem.personality.session_adaptations}")
    assert len(final_mem.personality.session_adaptations) > 0

    print("  [PASS] Integration flow works end-to-end")
    return True


async def main():
    print("=" * 60)
    print("Mirror Agent - Full System Test")
    print("=" * 60)

    tests = [
        test_memory_cache,
        test_soul_engine,
        test_event_bus,
        test_signal_extractor,
        test_personality_evolver,
        test_blackboard,
        test_task_system,
        test_cognition_updater,
        test_core_memory_scheduler,
        test_integration_flow,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            result = await test()
            if result:
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
