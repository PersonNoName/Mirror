"""Personality evolver with isolated session adaptation and versioned slow evolution."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.evolution.candidate_pipeline import EvolutionCandidate, EvolutionCandidateManager
from app.evolution.event_bus import EvolutionEntry, InteractionSignal
from app.memory.core_memory import BehavioralRule, PersonalityState, utc_now_iso
from app.platform.base import HitlRequest
from app.tasks.models import EvolutionCandidateRequest, Task


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PersonalityEvolver:
    """Manage short-lived session adaptation and slower long-term personality change."""

    FAST_MAX_ADAPTATIONS = 5
    SIGNAL_CONFIRMATION = 3
    DRIFT_THRESHOLD = 0.3
    TRAIT_DELTA_THRESHOLD = 0.18
    STYLE_DELTA_THRESHOLD = 0.2
    RULE_PROMOTION_LIMIT = 2
    SESSION_ADAPTATION_TTL_HOURS = 4

    def __init__(
        self,
        *,
        session_context_store: Any,
        core_memory_cache: Any,
        core_memory_scheduler: Any,
        evolution_journal: Any,
        snapshot_store: Any,
        candidate_manager: EvolutionCandidateManager | None = None,
        task_store: Any | None = None,
        blackboard: Any | None = None,
    ) -> None:
        self.session_context_store = session_context_store
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.evolution_journal = evolution_journal
        self.snapshot_store = snapshot_store
        self.candidate_manager = candidate_manager or EvolutionCandidateManager(evolution_journal)
        self.task_store = task_store
        self.blackboard = blackboard
        self._signal_buffer: dict[str, list[InteractionSignal]] = defaultdict(list)

    async def fast_adapt(self, signal: InteractionSignal) -> str | None:
        """Apply bounded short-term session adaptation without mutating long-term personality."""

        if self.session_context_store is None:
            return None
        try:
            adaptations = await self.session_context_store.get_adaptations(signal.user_id, signal.session_id)
        except Exception:
            return None
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
                event_type="session_adaptation_applied",
                summary=signal.content,
                details={"signal_type": signal.signal_type, "session_id": signal.session_id},
            )
        )
        return signal.content

    async def slow_evolve(self, user_id: str) -> None:
        """Submit long-term personality candidates and apply only approved changes."""

        current = deepcopy(await self.core_memory_cache.get(user_id))
        personality = deepcopy(current.personality)
        proposals = self._build_long_term_proposals(user_id, personality)
        if not proposals:
            return

        applicable: list[EvolutionCandidate] = []
        for proposal in proposals:
            submission = await self.candidate_manager.submit(
                user_id=user_id,
                affected_area=proposal["affected_area"],
                dedupe_key=proposal["dedupe_key"],
                proposed_change=proposal["proposed_change"],
                evidence_summary=proposal["summary"],
                rationale=proposal["rationale"],
                risk_level=proposal["risk_level"],
                source_event_id=proposal["source_event_id"],
                source_context_id=proposal["source_context_id"],
                metadata={"owner": "personality_evolver", "kind": proposal["kind"]},
            )
            if submission.action == "apply":
                applicable.append(submission.candidate)
            elif submission.action == "hitl":
                await self._create_evolution_candidate_task(user_id, submission.candidate)

        if applicable:
            await self._apply_personality_candidates(user_id, applicable)
        self._signal_buffer[user_id] = []

    async def apply_candidates(
        self,
        user_id: str,
        candidates: list[EvolutionCandidate],
        *,
        event_id: str | None = None,
    ) -> None:
        """Apply already-approved personality or relationship-style candidates."""

        if not candidates:
            return
        await self._apply_personality_candidates(user_id, candidates, event_id=event_id)

    async def handle_hitl_feedback(self, event: Any) -> None:
        if self.task_store is None:
            return
        task_id = str(event.payload.get("task_id", ""))
        if not task_id:
            return
        task = await self.task_store.get(task_id)
        if task is None:
            return
        metadata = dict(task.metadata.get("evolution_candidate", {}))
        if not metadata:
            return
        if metadata.get("affected_area") not in {"personality", "relationship_style"}:
            return
        candidate_id = str(metadata.get("candidate_id", ""))
        candidate = self.candidate_manager.get_candidate(candidate_id)
        if candidate is None:
            return
        decision = str(event.payload.get("decision", ""))
        if decision == "approve":
            await self._apply_personality_candidates(candidate.user_id, [candidate], event_id=task.id)
            task.status = "done"
        elif decision == "reject":
            await self.candidate_manager.mark_reverted(candidate.id, "hitl_rejected")
            task.status = "done"
        else:
            task.status = "waiting_hitl"
        await self.task_store.update(task)

    def _promotable_rules(self, user_id: str) -> list[str]:
        counts: dict[str, int] = defaultdict(int)
        by_session: dict[str, set[str]] = defaultdict(set)
        for signal in self._signal_buffer[user_id]:
            counts[signal.content] += 1
            by_session[signal.content].add(signal.session_id)
        return [
            content
            for content, count in counts.items()
            if count >= self.SIGNAL_CONFIRMATION and len(by_session[content]) >= 2
        ]

    def _build_long_term_proposals(
        self,
        user_id: str,
        personality: PersonalityState,
    ) -> list[dict[str, Any]]:
        proposals: list[dict[str, Any]] = []
        existing_rules = {rule.rule for rule in personality.core_personality.behavioral_rules}
        signals = self._signal_buffer.get(user_id, [])
        for rule_text in self._promotable_rules(user_id)[: self.RULE_PROMOTION_LIMIT]:
            if rule_text in existing_rules:
                continue
            signal = next((item for item in signals if item.content == rule_text), None)
            proposals.append(
                {
                    "kind": "behavioral_rule",
                    "affected_area": "personality",
                    "dedupe_key": f"rule:{self._normalize_rule(rule_text)}",
                    "proposed_change": {"kind": "behavioral_rule", "rule": rule_text},
                    "summary": f"Promote stable rule: {rule_text}",
                    "rationale": "Repeated multi-session session adaptations qualified for long-term rule promotion.",
                    "risk_level": "low",
                    "source_event_id": getattr(signal, "source_event_id", None)
                    or f"rule:{self._normalize_rule(rule_text)}:{self._source_context_for(signal)}",
                    "source_context_id": self._source_context_for(signal),
                }
            )

        for trait_name, delta in self._trait_deltas(user_id).items():
            signal = next(
                (item for item in signals if trait_name in self._trait_fields_for_signal(item.signal_type)),
                None,
            )
            proposals.append(
                {
                    "kind": "trait_update",
                    "affected_area": "personality",
                    "dedupe_key": f"trait:{trait_name}",
                    "proposed_change": {"kind": "trait_update", "field": trait_name, "delta": delta},
                    "summary": f"Adjust trait {trait_name} by {delta:.2f}",
                    "rationale": "Repeated interaction signals indicated a stable trait adjustment.",
                    "risk_level": self._trait_risk(abs(delta)),
                    "source_event_id": getattr(signal, "source_event_id", None)
                    or f"trait:{trait_name}:{self._source_context_for(signal)}",
                    "source_context_id": self._source_context_for(signal),
                }
            )

        for field_name, delta in self._style_deltas(user_id).items():
            signal = next((item for item in signals if item.signal_type.startswith(("tone_", "support_"))), None)
            proposals.append(
                {
                    "kind": "relationship_style",
                    "affected_area": "relationship_style",
                    "dedupe_key": f"relationship_style:{field_name}",
                    "proposed_change": {"kind": "relationship_style", "field": field_name, "delta": delta},
                    "summary": f"Adjust relationship style {field_name} by {delta:.2f}",
                    "rationale": "Repeated relationship-oriented signals indicated a longer-lived style adjustment.",
                    "risk_level": self._style_risk(abs(delta)),
                    "source_event_id": getattr(signal, "source_event_id", None)
                    or f"style:{field_name}:{self._source_context_for(signal)}",
                    "source_context_id": self._source_context_for(signal),
                }
            )
        return proposals

    def _trait_deltas(self, user_id: str) -> dict[str, float]:
        deltas: dict[str, float] = defaultdict(float)
        for signal in self._signal_buffer.get(user_id, []):
            if signal.signal_type == "tone_direct":
                deltas["directness"] += 0.05
            elif signal.signal_type == "prefer_concise":
                deltas["conciseness"] += 0.05
            elif signal.signal_type == "support_more":
                deltas["supportiveness"] += 0.05
        return {key: min(0.25, value) for key, value in deltas.items() if value}

    def _style_deltas(self, user_id: str) -> dict[str, float]:
        deltas: dict[str, float] = defaultdict(float)
        for signal in self._signal_buffer.get(user_id, []):
            if signal.signal_type == "tone_direct":
                deltas["boundary_strength"] += 0.05
                deltas["warmth"] -= 0.03
            elif signal.signal_type == "support_more":
                deltas["supportiveness"] += 0.08
        return {key: value for key, value in deltas.items() if value}

    async def _apply_personality_candidates(
        self,
        user_id: str,
        candidates: list[EvolutionCandidate],
        *,
        event_id: str | None = None,
    ) -> None:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        personality = deepcopy(current.personality)
        before = deepcopy(personality)
        snapshot = await self.snapshot_store.save(user_id, before, reason="pre_candidate_apply")
        personality.snapshot_version = snapshot.version
        personality.last_snapshot_at = snapshot.created_at

        changed = False
        promoted_rules: list[str] = []
        for candidate in candidates:
            if self._apply_candidate_to_personality(personality, candidate):
                changed = True
                if candidate.proposed_change.get("kind") == "behavioral_rule":
                    promoted_rules.append(str(candidate.proposed_change.get("rule", "")))

        if not changed:
            for candidate in candidates:
                await self.candidate_manager.mark_applied(candidate.id)
            return

        personality.core_personality.version += 1
        personality.core_personality.updated_at = utc_now_iso()
        personality.version += 1
        personality.core_personality.baseline_description = await self._regenerate_baseline(personality)
        personality.session_adaptation.current_items = []
        personality.session_adaptation.session_id = ""
        personality.session_adaptation.created_at = utc_now_iso()
        personality.session_adaptation.expires_at = utc_now_iso()

        if self._detect_drift(before, personality):
            rolled_back = await self.snapshot_store.rollback(user_id)
            if rolled_back is not None:
                rolled_back.rollback_count += 1
                rolled_back.last_snapshot_at = utc_now_iso()
                current.personality = rolled_back
                await self.core_memory_scheduler.write(user_id, "personality", rolled_back)
            for candidate in candidates:
                await self.candidate_manager.mark_reverted(candidate.id, "drift_detected")
            await self.evolution_journal.record(
                EvolutionEntry(
                    user_id=user_id,
                    event_type="personality_rollback",
                    summary="Personality drift detected; rolled back to the last snapshot.",
                    details={
                        "snapshot_version": snapshot.version,
                        "candidate_ids": [candidate.id for candidate in candidates],
                    },
                )
            )
            return

        current.personality = personality
        await self.core_memory_scheduler.write(user_id, "personality", personality, event_id=event_id)
        for candidate in candidates:
            await self.candidate_manager.mark_applied(candidate.id)
        for rule_text in promoted_rules:
            await self.evolution_journal.record(
                EvolutionEntry(user_id=user_id, event_type="rule_promoted", summary=rule_text, details={})
            )
        await self.evolution_journal.record(
            EvolutionEntry(
                user_id=user_id,
                event_type="personality_evolved",
                summary=personality.core_personality.baseline_description,
                details={"version": personality.version, "candidate_ids": [candidate.id for candidate in candidates]},
            )
        )

    def _apply_candidate_to_personality(
        self,
        personality: PersonalityState,
        candidate: EvolutionCandidate,
    ) -> bool:
        kind = str(candidate.proposed_change.get("kind", ""))
        if kind == "behavioral_rule":
            rule_text = str(candidate.proposed_change.get("rule", ""))
            existing = [rule.rule for rule in personality.core_personality.behavioral_rules]
            if not rule_text or rule_text in existing:
                return False
            personality.core_personality.behavioral_rules.append(
                BehavioralRule(rule=rule_text, confidence=0.8, source="candidate_pipeline")
            )
            return True
        if kind == "trait_update":
            field_name = str(candidate.proposed_change.get("field", ""))
            delta = float(candidate.proposed_change.get("delta", 0.0))
            if not field_name or delta == 0.0:
                return False
            traits = dict(personality.core_personality.traits_internal)
            traits[field_name] = min(1.0, max(0.0, traits.get(field_name, 0.0) + delta))
            personality.core_personality.traits_internal = traits
            return True
        if kind == "relationship_style":
            field_name = str(candidate.proposed_change.get("field", ""))
            delta = float(candidate.proposed_change.get("delta", 0.0))
            if not field_name or delta == 0.0 or not hasattr(personality.relationship_style, field_name):
                return False
            current_value = float(getattr(personality.relationship_style, field_name))
            setattr(personality.relationship_style, field_name, min(1.0, max(0.0, current_value + delta)))
            personality.relationship_style.updated_at = utc_now_iso()
            return True
        return False

    async def _create_evolution_candidate_task(
        self,
        user_id: str,
        candidate: EvolutionCandidate,
    ) -> None:
        if self.task_store is None or self.blackboard is None:
            return
        if candidate.metadata.get("hitl_task_id"):
            return
        payload = EvolutionCandidateRequest(
            candidate_id=candidate.id,
            affected_area=candidate.affected_area,
            risk_level=candidate.risk_level,
            evidence_summary=candidate.evidence_summary,
            proposed_change=dict(candidate.proposed_change),
            reason="This personality evolution candidate is high-risk and requires explicit approval.",
            metadata={"source_event_ids": list(candidate.source_event_ids)},
        )
        task = Task(
            intent="evolution_candidate_review",
            status="pending",
            metadata={"user_id": user_id, "evolution_candidate": asdict(payload)},
        )
        await self.task_store.create(task)
        self.candidate_manager.attach_hitl_task(candidate.id, task.id)
        request = HitlRequest(
            task_id=task.id,
            title="Personality evolution approval required",
            description=payload.reason,
            options=list(payload.options),
            risk_level=candidate.risk_level,
            metadata={"evolution_candidate": asdict(payload)},
        )
        await self.blackboard.on_task_waiting_hitl(task, request)

    def _detect_drift(self, before: PersonalityState, after: PersonalityState) -> bool:
        rule_delta = abs(
            len(after.core_personality.behavioral_rules) - len(before.core_personality.behavioral_rules)
        )
        if rule_delta > self.RULE_PROMOTION_LIMIT:
            return True

        if self._max_trait_delta(before.core_personality.traits_internal, after.core_personality.traits_internal) > self.TRAIT_DELTA_THRESHOLD:
            return True

        if self._style_delta(before, after) > self.STYLE_DELTA_THRESHOLD:
            return True

        baseline = after.core_personality.baseline_description.strip()
        if not baseline and (
            after.core_personality.behavioral_rules or after.core_personality.traits_internal
        ):
            return True
        return False

    @staticmethod
    def _max_trait_delta(before: dict[str, float], after: dict[str, float]) -> float:
        keys = set(before) | set(after)
        if not keys:
            return 0.0
        return max(abs(after.get(key, 0.0) - before.get(key, 0.0)) for key in keys)

    @staticmethod
    def _style_delta(before: PersonalityState, after: PersonalityState) -> float:
        deltas = [
            abs(after.relationship_style.warmth - before.relationship_style.warmth),
            abs(after.relationship_style.boundary_strength - before.relationship_style.boundary_strength),
            abs(after.relationship_style.supportiveness - before.relationship_style.supportiveness),
            abs(after.relationship_style.humor - before.relationship_style.humor),
        ]
        return max(deltas) if deltas else 0.0

    @staticmethod
    async def _regenerate_baseline(personality: PersonalityState) -> str:
        rules = [rule.rule for rule in personality.core_personality.behavioral_rules[-3:]]
        if not rules:
            return personality.core_personality.baseline_description or "Calm, direct, collaborative."
        return ", ".join(rules[:2])

    @classmethod
    def build_session_adaptation_state(cls, session_id: str, items: list[str]) -> dict[str, str | int | list[str]]:
        created_at = _utc_now()
        expires_at = created_at + timedelta(hours=cls.SESSION_ADAPTATION_TTL_HOURS)
        return {
            "current_items": list(items[-cls.FAST_MAX_ADAPTATIONS :]),
            "session_id": session_id,
            "created_at": created_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "max_items": cls.FAST_MAX_ADAPTATIONS,
        }

    @staticmethod
    def _normalize_rule(rule_text: str) -> str:
        return " ".join(rule_text.lower().split())

    @staticmethod
    def _source_context_for(signal: InteractionSignal | None) -> str:
        if signal is None:
            return ""
        return signal.session_id or signal.source_event_id or signal.content

    @staticmethod
    def _trait_fields_for_signal(signal_type: str) -> tuple[str, ...]:
        mapping = {
            "tone_direct": ("directness",),
            "prefer_concise": ("conciseness",),
            "support_more": ("supportiveness",),
        }
        return mapping.get(signal_type, ())

    def _trait_risk(self, delta: float) -> str:
        if delta >= self.TRAIT_DELTA_THRESHOLD:
            return "high"
        if delta >= self.TRAIT_DELTA_THRESHOLD * 0.7:
            return "medium"
        return "low"

    def _style_risk(self, delta: float) -> str:
        if delta >= self.STYLE_DELTA_THRESHOLD:
            return "high"
        if delta >= self.STYLE_DELTA_THRESHOLD * 0.5:
            return "medium"
        return "low"
