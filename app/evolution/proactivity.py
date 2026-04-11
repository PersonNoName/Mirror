"""Gentle proactive follow-up policy and orchestration."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.evolution.event_bus import EvolutionEntry
from app.memory.core_memory import (
    CoreMemory,
    ProactivityOpportunity,
    ProactivityPreference,
    ProactivityState,
    WorldModel,
    utc_now_iso,
)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class ProactivityDecision:
    """Structured result for proactive follow-up eligibility."""

    eligible: bool
    reason: str
    topic_key: str = ""
    draft_message: str = ""
    importance: str = "low"
    relationship_stage: str = "unfamiliar"
    stored_preference: str = "unknown"
    conservative_reference: str = ""


class GentleProactivityService:
    """Capture bounded follow-up opportunities and enforce low-intrusion policy."""

    def __init__(
        self,
        *,
        core_memory_cache: Any,
        core_memory_scheduler: Any,
        evolution_journal: Any | None = None,
    ) -> None:
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.evolution_journal = evolution_journal
        self.degraded = False

    async def handle_dialogue_ended(self, event: Any) -> None:
        payload = dict(getattr(event, "payload", {}))
        await self.capture_dialogue(
            user_id=str(payload.get("user_id", "")),
            session_id=str(payload.get("session_id", "")),
            user_text=str(payload.get("text", "")),
            reply_text=str(payload.get("reply", "")),
            event_id=str(getattr(event, "id", "")) or None,
        )

    async def capture_dialogue(
        self,
        *,
        user_id: str,
        session_id: str,
        user_text: str,
        reply_text: str = "",
        event_id: str | None = None,
    ) -> ProactivityState:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        state = world_model.proactivity_state
        state.last_user_message_at = utc_now_iso()

        override = self._detect_preference_override(user_text)
        if override != "unknown":
            state.latest_preference_override = override
            state.preference_updated_at = utc_now_iso()
            if override == "suppress":
                state.last_suppression_reason = "user_requested_no_followup"

        opportunity = self._extract_opportunity(user_text=user_text, session_id=session_id, world_model=world_model)
        changed = override != "unknown"
        if opportunity is not None:
            changed = self._merge_opportunity(state, opportunity) or changed
        state.pending_opportunities = self._prune_opportunities(state.pending_opportunities)
        state.recent_outreach = self._prune_recent_outreach(
            state.recent_outreach,
            window_hours=max(world_model.proactivity_policy.same_topic_cooldown_hours, 14 * 24),
        )
        if changed:
            await self.core_memory_scheduler.write(user_id, "world_model", world_model, event_id=event_id)
            await self._record(
                user_id=user_id,
                event_type="proactivity_opportunity_captured",
                summary="Captured bounded proactive follow-up context.",
                details={
                    "topic_key": opportunity.topic_key if opportunity is not None else "",
                    "importance": opportunity.importance if opportunity is not None else "low",
                    "preference_override": override,
                },
            )
        return deepcopy(state)

    async def plan_follow_up(
        self,
        *,
        user_id: str,
        now: datetime | None = None,
    ) -> ProactivityDecision:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        policy = world_model.proactivity_policy
        state = world_model.proactivity_state
        stage = world_model.relationship_stage.stage
        preference = self._resolve_preference(world_model)
        opportunities = [item for item in self._prune_opportunities(state.pending_opportunities) if item.status == "pending"]

        if not policy.enabled:
            return self._decision(False, "proactivity_disabled", stage, preference)
        if preference == "suppress":
            state.last_suppression_reason = "user_preference_suppressed"
            return self._decision(False, "user_preference_suppressed", stage, preference)
        if not opportunities:
            return self._decision(False, "no_pending_topic", stage, preference)

        candidate = self._select_opportunity(opportunities)
        if stage == "unfamiliar":
            state.last_suppression_reason = "relationship_stage_unfamiliar"
            return self._decision(False, "relationship_stage_unfamiliar", stage, preference, candidate)
        if stage == "repair_and_recovery":
            state.last_suppression_reason = "relationship_repair_active"
            return self._decision(False, "relationship_repair_active", stage, preference, candidate)
        if stage == "trust_building" and preference != "allow" and candidate.importance != "high":
            state.last_suppression_reason = "trust_building_requires_higher_importance"
            return self._decision(False, "trust_building_requires_higher_importance", stage, preference, candidate)
        if self._under_interval(state, policy.min_interval_hours, now=now):
            state.last_suppression_reason = "followup_interval_throttled"
            return self._decision(False, "followup_interval_throttled", stage, preference, candidate)
        if self._same_topic_recent(state, candidate.topic_key, policy.same_topic_cooldown_hours, now=now):
            state.last_suppression_reason = "same_topic_cooldown"
            return self._decision(False, "same_topic_cooldown", stage, preference, candidate)
        if self._too_many_recent_followups(state, policy.max_followups_per_14_days, now=now):
            state.last_suppression_reason = "frequency_cap_reached"
            return self._decision(False, "frequency_cap_reached", stage, preference, candidate)

        draft = self._draft_follow_up(candidate, stage=stage)
        return self._decision(True, "eligible", stage, preference, candidate, draft_message=draft)

    async def mark_follow_up_sent(
        self,
        *,
        user_id: str,
        topic_key: str,
        now: datetime | None = None,
        event_id: str | None = None,
    ) -> None:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        state = world_model.proactivity_state
        sent_at = (now or datetime.now(timezone.utc)).isoformat()
        state.last_proactive_at = sent_at
        state.last_topic_key = topic_key
        state.last_suppression_reason = ""
        state.recent_outreach.append({"topic_key": topic_key, "sent_at": sent_at})
        state.recent_outreach = self._prune_recent_outreach(
            state.recent_outreach,
            window_hours=max(world_model.proactivity_policy.same_topic_cooldown_hours, 14 * 24),
        )
        for item in state.pending_opportunities:
            if item.topic_key == topic_key:
                item.status = "sent"
                item.updated_at = sent_at
        await self.core_memory_scheduler.write(user_id, "world_model", world_model, event_id=event_id)
        await self._record(
            user_id=user_id,
            event_type="proactivity_followup_sent",
            summary="Recorded a bounded proactive follow-up.",
            details={"topic_key": topic_key},
        )

    def prompt_policy_snapshot(self, core_memory: CoreMemory) -> dict[str, Any]:
        world_model = core_memory.world_model
        state = world_model.proactivity_state
        preference = self._resolve_preference(world_model)
        pending = [item for item in self._prune_opportunities(state.pending_opportunities) if item.status == "pending"]
        return {
            "enabled": world_model.proactivity_policy.enabled,
            "stored_preference": preference,
            "last_proactive_at": state.last_proactive_at or "never",
            "pending_followup_count": len(pending),
            "last_suppression_reason": state.last_suppression_reason or "none",
            "policy_hint": (
                "Only follow up when relationship stage allows it, the topic is important, and throttle windows are clear."
            ),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "gentle_proactivity_enabled": True,
            "gentle_proactivity_degraded": self.degraded,
            "status": "degraded" if self.degraded else "ok",
        }

    @staticmethod
    def _detect_preference_override(text: str) -> ProactivityPreference:
        normalized = text.lower()
        allow_tokens = (
            "check in later",
            "follow up later",
            "feel free to check in",
            "ask me about it later",
            "you can remind me later",
        )
        suppress_tokens = (
            "don't remind me",
            "do not remind me",
            "don't follow up",
            "do not follow up",
            "don't check in",
            "no reminders",
            "don't ask me about this later",
        )
        if any(token in normalized for token in suppress_tokens):
            return "suppress"
        if any(token in normalized for token in allow_tokens):
            return "allow"
        return "unknown"

    @classmethod
    def _extract_opportunity(
        cls,
        *,
        user_text: str,
        session_id: str,
        world_model: WorldModel,
    ) -> ProactivityOpportunity | None:
        normalized = user_text.lower().strip()
        if not normalized or cls._contains_high_risk_signal(normalized):
            return None
        importance = cls._topic_importance(normalized)
        if importance == "low":
            return None
        summary = cls._conservative_summary(user_text)
        if not summary:
            return None
        return ProactivityOpportunity(
            topic_key=cls._topic_key(summary),
            summary=summary,
            importance=importance,
            session_id=session_id,
            source="dialogue",
            status="pending",
            conservative_reference=summary,
            metadata={"relationship_stage": world_model.relationship_stage.stage},
        )

    @staticmethod
    def _contains_high_risk_signal(text: str) -> bool:
        return any(
            token in text
            for token in ("kill myself", "suicide", "hurt myself", "hurt someone", "end my life")
        )

    @staticmethod
    def _topic_importance(text: str) -> str:
        high_tokens = (
            "interview",
            "exam",
            "deadline",
            "presentation",
            "surgery",
            "diagnosis",
            "court",
            "hospital",
            "tomorrow",
            "tonight",
            "next week",
            "breakup",
            "grief",
        )
        medium_tokens = (
            "anxious",
            "overwhelmed",
            "worried",
            "stressed",
            "hard",
            "difficult",
            "rough",
            "important",
            "family",
            "job",
            "move",
            "meeting",
        )
        if any(token in text for token in high_tokens):
            return "high"
        if any(token in text for token in medium_tokens):
            return "medium"
        return "low"

    @staticmethod
    def _conservative_summary(text: str) -> str:
        cleaned = " ".join(text.strip().split())
        if not cleaned:
            return ""
        sentence = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0].strip()
        return sentence[:160]

    @staticmethod
    def _topic_key(summary: str) -> str:
        tokens = re.findall(r"[a-z0-9]+", summary.lower())[:10]
        return ":".join(tokens) if tokens else "general-followup"

    @staticmethod
    def _merge_opportunity(state: ProactivityState, candidate: ProactivityOpportunity) -> bool:
        rank = {"low": 0, "medium": 1, "high": 2}
        for item in state.pending_opportunities:
            if item.topic_key != candidate.topic_key:
                continue
            if item.status == "sent":
                item.status = "pending"
            item.summary = candidate.summary
            if rank.get(candidate.importance, 0) > rank.get(item.importance, 0):
                item.importance = candidate.importance
            item.updated_at = utc_now_iso()
            item.session_id = candidate.session_id
            item.conservative_reference = candidate.conservative_reference
            return True
        state.pending_opportunities.append(candidate)
        return True

    @staticmethod
    def _prune_opportunities(items: list[ProactivityOpportunity]) -> list[ProactivityOpportunity]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        kept: list[ProactivityOpportunity] = []
        for item in items:
            updated_at = _parse_iso(item.updated_at or item.created_at)
            if updated_at is None or updated_at >= cutoff:
                kept.append(item)
        return kept

    @staticmethod
    def _prune_recent_outreach(items: list[dict[str, Any]], *, window_hours: int) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
        kept: list[dict[str, Any]] = []
        for item in items:
            sent_at = _parse_iso(str(item.get("sent_at", "")))
            if sent_at is None or sent_at >= cutoff:
                kept.append(dict(item))
        return kept

    @staticmethod
    def _resolve_preference(world_model: WorldModel) -> ProactivityPreference:
        override = world_model.proactivity_state.latest_preference_override
        if override != "unknown":
            return override
        for entry in world_model.confirmed_facts + world_model.inferred_memories:
            key = str(getattr(entry, "memory_key", ""))
            if not key.startswith("proactivity_preference:"):
                continue
            _, _, preference = key.partition(":")
            if preference in {"allow", "suppress"}:
                return preference
        return "unknown"

    @staticmethod
    def _select_opportunity(opportunities: list[ProactivityOpportunity]) -> ProactivityOpportunity:
        rank = {"high": 0, "medium": 1, "low": 2}
        return sorted(
            opportunities,
            key=lambda item: (rank.get(item.importance, 2), item.updated_at or item.created_at),
        )[0]

    @staticmethod
    def _under_interval(state: ProactivityState, hours: int, *, now: datetime | None) -> bool:
        if not state.last_proactive_at:
            return False
        sent_at = _parse_iso(state.last_proactive_at)
        if sent_at is None:
            return False
        current = now or datetime.now(timezone.utc)
        return sent_at > current - timedelta(hours=hours)

    @staticmethod
    def _same_topic_recent(state: ProactivityState, topic_key: str, hours: int, *, now: datetime | None) -> bool:
        current = now or datetime.now(timezone.utc)
        for item in state.recent_outreach:
            if str(item.get("topic_key", "")) != topic_key:
                continue
            sent_at = _parse_iso(str(item.get("sent_at", "")))
            if sent_at is not None and sent_at > current - timedelta(hours=hours):
                return True
        return False

    @staticmethod
    def _too_many_recent_followups(state: ProactivityState, max_followups: int, *, now: datetime | None) -> bool:
        current = now or datetime.now(timezone.utc)
        recent = 0
        for item in state.recent_outreach:
            sent_at = _parse_iso(str(item.get("sent_at", "")))
            if sent_at is not None and sent_at > current - timedelta(days=14):
                recent += 1
        return recent >= max_followups

    @staticmethod
    def _draft_follow_up(opportunity: ProactivityOpportunity, *, stage: str) -> str:
        if stage == "vulnerable_support":
            return (
                f"Earlier you mentioned {opportunity.conservative_reference}. "
                "No pressure to reply if you'd rather not, but how is that feeling now?"
            )
        return (
            f"Earlier you mentioned {opportunity.conservative_reference}. "
            "No pressure to reply, but I wanted to check in on how that's going."
        )

    @staticmethod
    def _decision(
        eligible: bool,
        reason: str,
        stage: str,
        preference: str,
        opportunity: ProactivityOpportunity | None = None,
        *,
        draft_message: str = "",
    ) -> ProactivityDecision:
        return ProactivityDecision(
            eligible=eligible,
            reason=reason,
            topic_key=opportunity.topic_key if opportunity is not None else "",
            draft_message=draft_message,
            importance=opportunity.importance if opportunity is not None else "low",
            relationship_stage=stage,
            stored_preference=preference,
            conservative_reference=opportunity.conservative_reference if opportunity is not None else "",
        )

    async def _record(
        self,
        *,
        user_id: str,
        event_type: str,
        summary: str,
        details: dict[str, Any],
    ) -> None:
        if self.evolution_journal is None:
            return
        await self.evolution_journal.record(
            EvolutionEntry(
                user_id=user_id,
                event_type=event_type,
                summary=summary,
                details=details,
            )
        )
