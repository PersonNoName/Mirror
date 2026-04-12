"""Cross-session mid-term memory storage and retrieval."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg

from app.config import settings
from app.memory.core_memory import utc_now_iso


MidTermMemoryStatus = str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _normalize_topic(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = re.sub(r"[^0-9a-z\u4e00-\u9fff _-]", "", text)
    return text[:120]


@dataclass(slots=True)
class MidTermMemoryItem:
    memory_key: str
    user_id: str
    content: str
    source: str = "dialogue"
    topic_key: str = ""
    memory_type: str = "topic"
    confidence: float = 0.0
    mention_count: int = 1
    first_seen_at: str = field(default_factory=utc_now_iso)
    last_seen_at: str = field(default_factory=utc_now_iso)
    last_recalled_at: str = ""
    strength: float = 0.55
    decay_score: float = 0.0
    expires_at: str = ""
    status: MidTermMemoryStatus = "active"
    session_ids: list[str] = field(default_factory=list)
    evidence_event_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class MidTermMemoryStore:
    """PostgreSQL-first store with memory fallback for recent cross-session continuity."""

    PROMOTION_MENTION_THRESHOLD = 3
    PROMOTION_SESSION_THRESHOLD = 2
    PROMOTION_WINDOW_DAYS = 30
    PROMOTION_RECENCY_DAYS = 14
    EXPIRY_DAYS = 21
    CLEANUP_RETENTION_DAYS = 45

    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or settings.postgres.dsn
        self._pool: asyncpg.Pool | None = None
        self._memory: dict[str, MidTermMemoryItem] = {}
        self.degraded = False
        self.degraded_reason: str | None = None
        self.storage_source = "postgres"

    async def initialize(self) -> None:
        pool = await self._get_pool()
        if pool is None:
            self.degraded = True
            if self.degraded_reason is None:
                self.degraded_reason = "postgres_unavailable"
            self.storage_source = "memory_fallback"
            return
        try:
            async with pool.acquire() as conn:
                exists = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = 'mid_term_memory'
                    )
                    """
                )
        except Exception:
            self.degraded = True
            self.degraded_reason = "postgres_unavailable"
            self.storage_source = "memory_fallback"
            return
        if not exists:
            self.degraded = True
            self.degraded_reason = "mid_term_memory_schema_missing"
            self.storage_source = "memory_fallback"
            return
        self.degraded = False
        self.degraded_reason = None
        self.storage_source = "postgres"

    async def _get_pool(self) -> asyncpg.Pool | None:
        if self.degraded:
            return None
        if self._pool is None:
            try:
                self._pool = await asyncpg.create_pool(dsn=self.dsn)
            except Exception:
                self.degraded = True
                self.degraded_reason = "postgres_unavailable"
                self.storage_source = "memory_fallback"
                return None
        return self._pool

    async def upsert_observation(
        self,
        *,
        user_id: str,
        session_id: str,
        topic_key: str,
        content: str,
        memory_type: str = "topic",
        source: str = "dialogue",
        confidence: float = 0.6,
        event_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MidTermMemoryItem:
        observed_at = (now or _utc_now()).astimezone(timezone.utc)
        normalized_topic = _normalize_topic(topic_key or content)
        memory_key = f"mid_term:{memory_type}:{normalized_topic}"
        item = self._memory.get(memory_key)
        expires_at = (observed_at + timedelta(days=self.EXPIRY_DAYS)).isoformat()
        if item is None:
            item = MidTermMemoryItem(
                memory_key=memory_key,
                user_id=user_id,
                content=content.strip(),
                source=source,
                topic_key=normalized_topic,
                memory_type=memory_type,
                confidence=max(0.0, min(confidence, 1.0)),
                mention_count=1,
                first_seen_at=observed_at.isoformat(),
                last_seen_at=observed_at.isoformat(),
                strength=max(0.55, min(confidence, 0.95)),
                decay_score=0.0,
                expires_at=expires_at,
                status="active",
                session_ids=[session_id] if session_id else [],
                evidence_event_ids=[event_id] if event_id else [],
                metadata=dict(metadata or {}),
            )
        elif item.status != "suppressed":
            item.content = content.strip() or item.content
            item.source = source or item.source
            item.confidence = max(item.confidence, max(0.0, min(confidence, 1.0)))
            item.mention_count += 1
            item.last_seen_at = observed_at.isoformat()
            item.strength = min(1.0, item.strength + 0.18)
            item.decay_score = 0.0
            item.expires_at = expires_at
            item.status = "active" if item.status == "expired" else item.status
            item.metadata.update(dict(metadata or {}))
            if session_id and session_id not in item.session_ids:
                item.session_ids.append(session_id)
            if event_id and event_id not in item.evidence_event_ids:
                item.evidence_event_ids.append(event_id)
        self._memory[memory_key] = item
        await self._persist(item)
        return self._clone(item)

    async def list_items(
        self,
        *,
        user_id: str,
        include_expired: bool = False,
        statuses: set[str] | None = None,
    ) -> list[MidTermMemoryItem]:
        await self._hydrate_user(user_id)
        items = [self._clone(item) for item in self._memory.values() if item.user_id == user_id]
        if not include_expired:
            items = [item for item in items if item.status != "expired"]
        if statuses is not None:
            items = [item for item in items if item.status in statuses]
        return sorted(items, key=lambda item: (item.last_seen_at, item.strength), reverse=True)

    async def retrieve(
        self,
        *,
        user_id: str,
        query: str,
        limit: int = 5,
        now: datetime | None = None,
    ) -> list[MidTermMemoryItem]:
        current_time = now or _utc_now()
        items = await self.list_items(user_id=user_id, include_expired=False, statuses={"active"})
        if not items:
            return []
        query_tokens = self._tokens(query)
        ranked: list[tuple[float, MidTermMemoryItem]] = []
        for item in items:
            score = self._rank_item(item, query_tokens=query_tokens, now=current_time)
            if score <= 0:
                continue
            ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        selected = [item for _, item in ranked[:limit]]
        for item in selected:
            await self.mark_recalled(user_id=user_id, memory_key=item.memory_key, now=current_time)
        return selected

    async def mark_recalled(self, *, user_id: str, memory_key: str, now: datetime | None = None) -> None:
        item = self._memory.get(memory_key)
        if item is None or item.user_id != user_id or item.status != "active":
            return
        recalled_at = (now or _utc_now()).astimezone(timezone.utc).isoformat()
        item.last_recalled_at = recalled_at
        item.strength = min(1.0, item.strength + 0.05)
        self._memory[memory_key] = item
        await self._persist(item)

    async def apply_decay(self, *, now: datetime | None = None) -> int:
        current_time = now or _utc_now()
        changed = 0
        for memory_key, item in list(self._memory.items()):
            if item.status in {"suppressed", "promoted"}:
                continue
            last_seen = _parse_iso(item.last_seen_at) or current_time
            days_since_seen = max(0.0, (current_time - last_seen).total_seconds() / 86400.0)
            item.decay_score = round(days_since_seen / max(self.EXPIRY_DAYS, 1), 4)
            item.strength = max(0.0, round(item.strength * math.exp(-0.08 * max(days_since_seen - 2, 0.0)), 4))
            if days_since_seen >= self.EXPIRY_DAYS:
                item.status = "expired"
            self._memory[memory_key] = item
            await self._persist(item)
            changed += 1
        return changed

    async def cleanup_expired(self, *, now: datetime | None = None) -> int:
        current_time = now or _utc_now()
        removed = 0
        for memory_key, item in list(self._memory.items()):
            last_seen = _parse_iso(item.last_seen_at) or current_time
            if item.status != "expired":
                continue
            if (current_time - last_seen).days < self.CLEANUP_RETENTION_DAYS:
                continue
            del self._memory[memory_key]
            removed += 1
            pool = await self._get_pool()
            if pool is not None:
                try:
                    async with pool.acquire() as conn:
                        await conn.execute("DELETE FROM mid_term_memory WHERE memory_key = $1", memory_key)
                except Exception:
                    self.degraded = True
        return removed

    async def maybe_promote(self, *, user_id: str, memory_key: str, now: datetime | None = None) -> MidTermMemoryItem | None:
        item = self._memory.get(memory_key)
        if item is None or item.user_id != user_id or item.status != "active":
            return None
        current_time = now or _utc_now()
        first_seen = _parse_iso(item.first_seen_at) or current_time
        last_seen = _parse_iso(item.last_seen_at) or current_time
        if (current_time - first_seen).days > self.PROMOTION_WINDOW_DAYS:
            return None
        if (current_time - last_seen).days > self.PROMOTION_RECENCY_DAYS:
            return None
        if item.mention_count < self.PROMOTION_MENTION_THRESHOLD:
            return None
        if len(set(item.session_ids)) < self.PROMOTION_SESSION_THRESHOLD:
            return None
        item.status = "promoted"
        item.metadata["promotion_ready_at"] = current_time.isoformat()
        self._memory[memory_key] = item
        await self._persist(item)
        return self._clone(item)

    async def mark_promoted(
        self,
        *,
        user_id: str,
        memory_key: str,
        promoted_memory_key: str,
    ) -> None:
        item = self._memory.get(memory_key)
        if item is None or item.user_id != user_id:
            return
        item.status = "promoted"
        item.metadata["promoted_memory_key"] = promoted_memory_key
        self._memory[memory_key] = item
        await self._persist(item)

    async def suppress_related(
        self,
        *,
        user_id: str,
        memory_key: str | None = None,
        content: str | None = None,
        reason: str = "",
    ) -> list[str]:
        await self._hydrate_user(user_id)
        suppressed: list[str] = []
        query_tokens = self._tokens(content or memory_key or "")
        for item_key, item in list(self._memory.items()):
            if item.user_id != user_id or item.status == "suppressed":
                continue
            promoted_key = str(item.metadata.get("promoted_memory_key", ""))
            if memory_key and (item_key == memory_key or promoted_key == memory_key):
                item.status = "suppressed"
            elif query_tokens and query_tokens.intersection(self._tokens(item.content + " " + item.topic_key)):
                item.status = "suppressed"
            else:
                continue
            item.metadata["suppressed_reason"] = reason
            self._memory[item_key] = item
            await self._persist(item)
            suppressed.append(item_key)
        return suppressed

    @staticmethod
    def serialize_item(item: MidTermMemoryItem) -> dict[str, Any]:
        return {
            "memory_key": item.memory_key,
            "content": item.content,
            "truth_type": "mid_term",
            "status": item.status,
            "source": item.source,
            "confidence": item.confidence,
            "confirmed_by_user": False,
            "updated_at": item.last_seen_at or item.first_seen_at,
            "visibility": "mid_term",
        }

    def _rank_item(self, item: MidTermMemoryItem, *, query_tokens: set[str], now: datetime) -> float:
        last_seen = _parse_iso(item.last_seen_at) or now
        recency_days = max(0.0, (now - last_seen).total_seconds() / 86400.0)
        overlap = 0.0
        if query_tokens:
            item_tokens = self._tokens(item.content + " " + item.topic_key)
            overlap = len(query_tokens.intersection(item_tokens)) / max(len(query_tokens), 1)
        recency_bonus = max(0.0, 1.0 - recency_days / max(self.EXPIRY_DAYS, 1))
        strength_score = max(0.0, item.strength - item.decay_score)
        if overlap <= 0 and recency_bonus <= 0:
            return 0.0
        return round(overlap * 0.55 + recency_bonus * 0.2 + strength_score * 0.25, 4)

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[0-9a-z\u4e00-\u9fff]{2,}", str(text or "").lower())
            if token
        }

    async def _hydrate_user(self, user_id: str) -> None:
        pool = await self._get_pool()
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT payload_json
                    FROM mid_term_memory
                    WHERE user_id = $1
                    """,
                    user_id,
                )
        except Exception:
            self.degraded = True
            self.degraded_reason = "postgres_unavailable"
            self.storage_source = "memory_fallback"
            return
        for row in rows:
            payload = row["payload_json"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            item = MidTermMemoryItem(**dict(payload))
            self._memory[item.memory_key] = item

    async def _persist(self, item: MidTermMemoryItem) -> None:
        pool = await self._get_pool()
        if pool is None:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO mid_term_memory (memory_key, user_id, topic_key, status, payload_json)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (memory_key)
                    DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        topic_key = EXCLUDED.topic_key,
                        status = EXCLUDED.status,
                        payload_json = EXCLUDED.payload_json
                    """,
                    item.memory_key,
                    item.user_id,
                    item.topic_key,
                    item.status,
                    json.dumps(asdict(item)),
                )
        except Exception:
            self.degraded = True
            if self.degraded_reason is None:
                self.degraded_reason = "postgres_unavailable"
            self.storage_source = "memory_fallback"

    @staticmethod
    def _clone(item: MidTermMemoryItem) -> MidTermMemoryItem:
        return MidTermMemoryItem(**asdict(item))
