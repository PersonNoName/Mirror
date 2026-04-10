"""Personality evolver with fast and slow paths."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from app.evolution.event_bus import EvolutionEntry, InteractionSignal
from app.memory.core_memory import BehavioralRule


class PersonalityEvolver:
    """Manage session adaptations and slower rule promotion."""

    FAST_MAX_ADAPTATIONS = 5
    SIGNAL_CONFIRMATION = 3
    DRIFT_THRESHOLD = 0.3

    def __init__(
        self,
        *,
        session_context_store: Any,
        core_memory_cache: Any,
        core_memory_scheduler: Any,
        evolution_journal: Any,
        snapshot_store: Any,
    ) -> None:
        self.session_context_store = session_context_store
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.evolution_journal = evolution_journal
        self.snapshot_store = snapshot_store
        self._signal_buffer: dict[str, list[InteractionSignal]] = defaultdict(list)

    async def fast_adapt(self, signal: InteractionSignal) -> str | None:
        if self.session_context_store is None:
            return None
        adaptations = await self.session_context_store.get_adaptations(signal.user_id, signal.session_id)
        if signal.content in adaptations:
            return signal.content
        if len(adaptations) >= self.FAST_MAX_ADAPTATIONS:
            adaptations = adaptations[-(self.FAST_MAX_ADAPTATIONS - 1) :]
        adaptations.append(signal.content)
        await self.session_context_store.set_adaptations(signal.user_id, signal.session_id, adaptations)
        self._signal_buffer[signal.user_id].append(signal)
        await self.evolution_journal.record(
            EvolutionEntry(
                user_id=signal.user_id,
                event_type="fast_adaptation",
                summary=signal.content,
                details={"signal_type": signal.signal_type, "session_id": signal.session_id},
            )
        )
        if self._ready_for_slow(signal.user_id, signal.signal_type):
            await self.slow_evolve(signal.user_id)
        return signal.content

    async def slow_evolve(self, user_id: str) -> None:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        personality = current.personality
        await self.snapshot_store.save(user_id, personality)
        promoted = self._promotable_rules(user_id)
        changed = False
        for rule_text in promoted:
            if rule_text not in [rule.rule for rule in personality.behavioral_rules]:
                personality.behavioral_rules.append(
                    BehavioralRule(rule=rule_text, confidence=0.8, source="slow_evolve")
                )
                changed = True
                await self.evolution_journal.record(
                    EvolutionEntry(user_id=user_id, event_type="rule_promoted", summary=rule_text, details={})
                )
        if not changed:
            return
        if self._detect_drift(personality):
            snapshot = await self.snapshot_store.latest(user_id)
            if snapshot is not None:
                personality = snapshot
            return
        personality.baseline_description = await self._regenerate_baseline(personality)
        await self.evolution_journal.record(
            EvolutionEntry(
                user_id=user_id,
                event_type="baseline_shifted",
                summary=personality.baseline_description,
                details={},
            )
        )
        await self.core_memory_scheduler.write(user_id, "personality", personality)
        self._signal_buffer[user_id] = []

    def _ready_for_slow(self, user_id: str, signal_type: str) -> bool:
        matches = [signal for signal in self._signal_buffer[user_id] if signal.signal_type == signal_type]
        return len(matches) >= self.SIGNAL_CONFIRMATION

    def _promotable_rules(self, user_id: str) -> list[str]:
        counts: dict[str, int] = defaultdict(int)
        for signal in self._signal_buffer[user_id]:
            counts[signal.content] += 1
        return [content for content, count in counts.items() if count >= self.SIGNAL_CONFIRMATION]

    @staticmethod
    def _detect_drift(personality: Any) -> bool:
        return len(personality.behavioral_rules) > 10

    @staticmethod
    async def _regenerate_baseline(personality: Any) -> str:
        rules = [rule.rule for rule in personality.behavioral_rules[-3:]]
        if not rules:
            return personality.baseline_description or "冷静、直接、合作式"
        return "；".join(rules[:2])
