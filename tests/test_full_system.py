import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json

from domain.task import Task
from domain.memory import CoreMemory, PersonalityState, BehavioralRule
from domain.evolution import InteractionSignal, Lesson

from core.memory_cache import CoreMemoryCache
from core.soul_engine import SoulEngine
from core.blackboard import Blackboard

from events.event_bus import EventBus, EVENT_BUS_CONFIG
from evolution.signal_extractor import SignalExtractor
from evolution.personality_evolver import PersonalityEvolver
from evolution.cognition_updater import CognitionUpdater
from evolution.evolution_journal import EvolutionJournal

from services.graph_db import GraphDBClient
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
        print("  [LLM] Generating response...")
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

    engine = SoulEngine(core_memory_cache=cache, vector_retriever=None, llm=DummyLLM())

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

    await task_system.create_task({"intent": "Low priority", "priority": 2})
    await task_system.create_task({"intent": "High priority", "priority": 0})
    await task_system.create_task({"intent": "Normal priority", "priority": 1})

    print("  Created 3 tasks with priorities 2, 0, 1")
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


async def test_chat_flow():
    print("\n=== Test 11: Full Chat Flow (SoulEngine + ActionRouter + Evolution) ===")

    cache = CoreMemoryCache()
    cache.set(
        "alice",
        CoreMemory(
            personality=PersonalityState(
                behavioral_rules=[
                    BehavioralRule(content="回复要简洁", source="test", confidence=0.9),
                ],
            )
        ),
    )

    journal = EvolutionJournal(journal_store=DummyJournalStore(), llm_lite=DummyLLM())
    extractor = SignalExtractor()
    evolver = PersonalityEvolver(
        core_memory_cache=cache,
        llm_lite=DummyLLM(),
        evolution_journal=journal,
    )

    event_bus = EventBus(EVENT_BUS_CONFIG)
    await event_bus.start()

    class DummyTaskSystem:
        async def create(self, task_spec):
            print(f"  [TaskSystem] Task created: {task_spec.get('intent', 'unknown')}")
            return Task(intent=task_spec.get("intent", ""), created_by="test")

        async def get(self, task_id):
            return None

    class DummyBlackboard:
        async def evaluate_agents(self, task):
            return None, 0.8

        async def assign(self, task, agent):
            print(f"  [Blackboard] Task assigned: {task.id}")

        async def resume(self, task_id, hitl_result):
            pass

    task_system = DummyTaskSystem()
    blackboard = DummyBlackboard()

    from core.action_router import ActionRouter, HITLGatewayDummy, ToolExecutorDummy

    router = ActionRouter(
        task_system=task_system,
        blackboard=blackboard,
        hitl_gateway=HITLGatewayDummy(),
        tool_executor=ToolExecutorDummy(),
        event_bus=event_bus,
    )

    soul_engine = SoulEngine(
        core_memory_cache=cache,
        vector_retriever=None,
        llm=DummyLLM(),
    )

    async def handle_dialogue_ended(event):
        dialogue = event.payload.get("dialogue", [])
        session_id = event.payload.get("session_id", "")
        user_id = event.payload.get("user_id", "")
        signals = await extractor.extract(dialogue, session_id, turn_index=0)
        for signal in signals:
            await evolver.fast_adapt(signal, user_id)
        print(f"  [Evolution] Processed {len(signals)} signals from dialogue_ended")

    await event_bus.subscribe("dialogue_ended", handle_dialogue_ended)

    print("  Step 1: Build prompt")
    prompt = await soul_engine.build_prompt(
        "alice", "session789", "你好，请用简洁的语言介绍自己"
    )
    print(f"  Prompt length: {len(prompt)} chars")
    assert len(prompt) > 100

    print("  Step 2: SoulEngine.think")
    think_result = await soul_engine.think(prompt)
    print(
        f"  Think result: action={think_result.get('action')}, content={think_result.get('content', '')[:50]}"
    )
    assert "action" in think_result
    assert "content" in think_result

    print("  Step 3: ActionRouter.route")
    route_result = await router.route(
        think_result, {"user_id": "alice", "session_id": "session789"}
    )
    print(
        f"  Route result: action={route_result.get('action')}, content={route_result.get('content', '')[:50]}"
    )

    print("  Step 4: Emit dialogue_ended event")
    await event_bus.emit(
        "dialogue_ended",
        {
            "user_id": "alice",
            "session_id": "session789",
            "dialogue": [
                {"role": "user", "content": "你好，请用简洁的语言介绍自己"},
                {"role": "assistant", "content": route_result.get("content", "")},
            ],
        },
    )
    await asyncio.sleep(0.2)

    final_mem = cache.get("alice")
    print(f"  Final session_adaptations: {final_mem.personality.session_adaptations}")

    await event_bus.stop()

    print("  [PASS] Full chat flow works end-to-end")
    return True


async def test_circuit_breaker():
    print("\n=== Test 12: CircuitBreaker ===")
    from domain.stability import CircuitBreaker, CircuitBreakerOpen

    cb = CircuitBreaker(
        name="test_llm",
        failure_threshold=3,
        success_threshold=2,
        open_timeout_seconds=1,
    )

    assert cb.state.state == "closed"
    print("  Initial state: closed")

    success_count = 0
    for i in range(3):
        try:
            await cb.call(lambda: asyncio.sleep(0))
            success_count += 1
        except Exception:
            pass
    assert success_count == 3
    print(f"  Closed: 3 successful calls, state={cb.state.state}")

    cb.record_failure()
    cb.record_failure()
    assert cb.state.state == "closed"
    cb.record_failure()
    assert cb.state.state == "open"
    print(f"  After 3 failures: state={cb.state.state} (OPEN)")

    try:
        await cb.call(lambda: asyncio.sleep(0))
        assert False, "Should have raised CircuitBreakerOpen"
    except CircuitBreakerOpen as e:
        print(f"  OPEN call rejected: {e}")

    import time

    time.sleep(1.1)
    assert cb.state.state == "half_open"
    print(f"  After timeout: state={cb.state.state} (HALF_OPEN)")

    cb.record_success()
    cb.record_success()
    assert cb.state.state == "closed"
    print(f"  After 2 successes: state={cb.state.state} (CLOSED)")

    print("  [PASS] CircuitBreaker state transitions work correctly")
    return True


async def test_core_memory_scheduler_compress():
    print("\n=== Test 13: CoreMemoryScheduler._compress (LLM) ===")
    cache = CoreMemoryCache()
    cache.set("test_user", CoreMemory())

    store = DummyCoreMemoryStore()

    class LLMForTest:
        async def generate(self, prompt):
            assert "self_cognition" in prompt
            return '{"summary": "压缩后的摘要：能力提升，掌握了新技术", "count": 5}'

    scheduler = CoreMemoryScheduler(
        core_memory_store=store,
        cache=cache,
        llm=LLMForTest(),
    )

    data_with_pinned = {
        "capability_map": {
            "code": {
                "domain": "code",
                "confidence": 0.9,
                "is_pinned": True,
                "known_limits": [],
            },
            "writing": {
                "domain": "writing",
                "confidence": 0.5,
                "is_pinned": False,
                "known_limits": [],
            },
        },
        "known_limits": [],
        "blindspots": [],
    }
    serialized = json.dumps(data_with_pinned)

    compressed = await scheduler._compress(serialized, "self_cognition")
    result = json.loads(compressed)

    assert "capability_map" in result
    assert result["capability_map"]["code"]["is_pinned"] is True
    assert "_compressed_summary" in result
    assert "summary" in result["_compressed_summary"]
    print(f"  Mixed pinned+non-pinned: pinned preserved, non-pinned compressed")
    print(f"  Compressed summary: {result['_compressed_summary']['summary']}")

    data_all_pinned = {
        "rules": [
            {"content": "保持简洁", "is_pinned": True},
            {"content": "技术优先", "is_pinned": True},
        ]
    }
    compressed_all = await scheduler._compress(
        json.dumps(data_all_pinned), "personality"
    )
    assert compressed_all == json.dumps(data_all_pinned)
    print("  All pinned: returned unchanged")

    scheduler_no_llm = CoreMemoryScheduler(
        core_memory_store=store,
        cache=cache,
        llm=None,
    )
    result_no_llm = await scheduler_no_llm._compress(
        json.dumps({"foo": "bar"}), "self_cognition"
    )
    assert result_no_llm == json.dumps({"foo": "bar"})
    print("  No LLM configured: returned unchanged")

    print("  [PASS] CoreMemoryScheduler._compress works correctly")
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
        test_chat_flow,
        test_circuit_breaker,
        test_core_memory_scheduler_compress,
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
