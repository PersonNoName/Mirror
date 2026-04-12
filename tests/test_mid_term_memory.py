from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest

from app.evolution.event_bus import Event
from app.evolution.mid_term_memory import MidTermMemoryExtractor
from app.memory.mid_term_memory import MidTermMemoryItem, MidTermMemoryStore
from tests.conftest import DummyMidTermMemoryStore


class RecordingEventBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def emit(self, event: Event) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_mid_term_memory_store_retrieves_across_sessions_and_promotes() -> None:
    store = MidTermMemoryStore(dsn="")
    store.degraded = True
    store.degraded_reason = "test_memory_only"
    store.storage_source = "memory_fallback"
    now = datetime(2026, 4, 12, tzinfo=timezone.utc)

    await store.upsert_observation(
        user_id="user-1",
        session_id="session-a",
        topic_key="mirror memory rollout",
        content="User is working on mirror memory rollout.",
        memory_type="project",
        now=now,
    )
    await store.upsert_observation(
        user_id="user-1",
        session_id="session-b",
        topic_key="mirror memory rollout",
        content="User is working on mirror memory rollout.",
        memory_type="project",
        now=now + timedelta(days=2),
    )
    item = await store.upsert_observation(
        user_id="user-1",
        session_id="session-b",
        topic_key="mirror memory rollout",
        content="User is working on mirror memory rollout.",
        memory_type="project",
        now=now + timedelta(days=3),
    )

    matches = await store.retrieve(user_id="user-1", query="continue the memory rollout", limit=3, now=now + timedelta(days=3))
    promoted = await store.maybe_promote(user_id="user-1", memory_key=item.memory_key, now=now + timedelta(days=3))

    assert matches
    assert matches[0].memory_key == item.memory_key
    assert matches[0].mention_count == 3
    assert promoted is not None
    assert promoted.status == "promoted"


@pytest.mark.asyncio
async def test_mid_term_memory_store_expires_stale_items() -> None:
    store = MidTermMemoryStore(dsn="")
    store.degraded = True
    store.degraded_reason = "test_memory_only"
    store.storage_source = "memory_fallback"
    first_seen = datetime(2026, 1, 1, tzinfo=timezone.utc)
    item = await store.upsert_observation(
        user_id="user-1",
        session_id="session-a",
        topic_key="legacy topic",
        content="User is working on a legacy topic.",
        memory_type="topic",
        now=first_seen,
    )

    await store.apply_decay(now=first_seen + timedelta(days=30))
    items = await store.list_items(user_id="user-1", include_expired=True)

    assert item.memory_key == items[0].memory_key
    assert items[0].status == "expired"


@pytest.mark.asyncio
async def test_mid_term_memory_extractor_emits_lesson_when_topic_repeats_across_sessions() -> None:
    store = MidTermMemoryStore(dsn="")
    store.degraded = True
    store.degraded_reason = "test_memory_only"
    store.storage_source = "memory_fallback"
    event_bus = RecordingEventBus()
    extractor = MidTermMemoryExtractor(mid_term_memory_store=store, event_bus=event_bus)

    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={"user_id": "user-1", "session_id": "session-a", "text": "I'm working on the mirror memory rollout", "reply": "ok"},
        )
    )
    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={"user_id": "user-1", "session_id": "session-b", "text": "I'm still working on the mirror memory rollout", "reply": "ok"},
        )
    )
    await extractor.handle_dialogue_ended(
        Event(
            type="dialogue_ended",
            payload={"user_id": "user-1", "session_id": "session-b", "text": "I'm now working on the mirror memory rollout", "reply": "ok"},
        )
    )

    assert event_bus.events
    lesson = event_bus.events[-1].payload["lesson"]
    assert lesson["domain"] == "mid_term_topic"
    assert lesson["details"]["mid_term_memory_key"].startswith("mid_term:project:")


def test_dummy_mid_term_store_matches_governance_contract() -> None:
    item = MidTermMemoryItem(
        memory_key="mid_term:topic:mirror",
        user_id="user-1",
        content="Mirror topic",
    )
    store = DummyMidTermMemoryStore(items=[item])

    assert store.items[0].memory_key == "mid_term:topic:mirror"


@pytest.mark.asyncio
async def test_mid_term_memory_initialize_succeeds_when_schema_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConn:
        async def fetchval(self, query: str) -> bool:
            return True

    class FakeAcquire:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakePool:
        def acquire(self) -> FakeAcquire:
            return FakeAcquire()

    async def create_pool(*args, **kwargs):
        return FakePool()

    monkeypatch.setattr("app.memory.mid_term_memory.asyncpg.create_pool", create_pool)
    store = MidTermMemoryStore()

    await store.initialize()

    assert store.degraded is False
    assert store.degraded_reason is None
    assert store.storage_source == "postgres"


@pytest.mark.asyncio
async def test_mid_term_memory_initialize_marks_schema_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConn:
        async def fetchval(self, query: str) -> bool:
            return False

    class FakeAcquire:
        async def __aenter__(self) -> FakeConn:
            return FakeConn()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    class FakePool:
        def acquire(self) -> FakeAcquire:
            return FakeAcquire()

    async def create_pool(*args, **kwargs):
        return FakePool()

    monkeypatch.setattr("app.memory.mid_term_memory.asyncpg.create_pool", create_pool)
    store = MidTermMemoryStore()

    await store.initialize()

    assert store.degraded is True
    assert store.degraded_reason == "mid_term_memory_schema_missing"
    assert store.storage_source == "memory_fallback"


@pytest.mark.asyncio
async def test_mid_term_memory_initialize_marks_postgres_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def create_pool(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.memory.mid_term_memory.asyncpg.create_pool", create_pool)
    store = MidTermMemoryStore()

    await store.initialize()

    assert store.degraded is True
    assert store.degraded_reason == "postgres_unavailable"
    assert store.storage_source == "memory_fallback"
