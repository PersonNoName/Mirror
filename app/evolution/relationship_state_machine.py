"""Candidate-driven relationship stage state machine."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any

from app.evolution.candidate_pipeline import EvolutionCandidate, EvolutionCandidateManager
from app.evolution.event_bus import EvolutionEntry
from app.memory.core_memory import CoreMemory, RelationshipStageState, utc_now_iso


class RelationshipStateMachine:
    """Derive a bounded relationship-stage snapshot from durable memory and dialogue evidence."""

    def __init__(
        self,
        *,
        core_memory_cache: Any,
        core_memory_scheduler: Any,
        candidate_manager: EvolutionCandidateManager | None = None,
        evolution_journal: Any | None = None,
        personality_evolver: Any | None = None,
    ) -> None:
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.candidate_manager = candidate_manager
        self.evolution_journal = evolution_journal
        self.personality_evolver = personality_evolver
        self.degraded = candidate_manager is None

    async def evaluate(
        self,
        *,
        user_id: str,
        observation: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> RelationshipStageState:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        proposed = self._derive_stage(current, observation)
        if self.candidate_manager is None:
            await self._apply_stage_candidate(
                user_id,
                {
                    "kind": "relationship_stage",
                    "relationship_stage": asdict(proposed),
                },
                event_id=event_id,
            )
            return proposed

        world_model = current.world_model
        previous = world_model.relationship_stage
        if self._stage_snapshot_equal(previous, proposed):
            return previous

        submission = await self.candidate_manager.submit(
            user_id=user_id,
            affected_area="world_model",
            dedupe_key="relationship_stage",
            proposed_change={
                "kind": "relationship_stage",
                "from_stage": previous.stage,
                "relationship_stage": asdict(proposed),
            },
            evidence_summary=proposed.recent_transition_reason or f"Relationship stage -> {proposed.stage}",
            rationale="Relationship stage transitions now use the controlled evolution pipeline.",
            risk_level=self._stage_risk(previous.stage, proposed.stage),
            source_event_id=event_id,
            source_context_id=str(observation.get("context_id", "")) if observation else event_id,
            metadata={
                "relationship_stage_from": previous.stage,
                "relationship_stage_to": proposed.stage,
                "transition_reason": proposed.recent_transition_reason,
            },
        )
        if submission.action == "apply":
            await self._apply_stage_candidate(user_id, submission.candidate.proposed_change, event_id=event_id)
            await self.candidate_manager.mark_applied(submission.candidate.id)
            await self._submit_style_adjustments(user_id, proposed, event_id=event_id)
        return proposed

    def prompt_policy_snapshot(self, core_memory: CoreMemory) -> dict[str, str | float | list[str]]:
        stage = core_memory.world_model.relationship_stage
        return {
            "stage": stage.stage,
            "confidence": stage.confidence,
            "reason": stage.recent_transition_reason or "No recent transition recorded.",
            "supports_vulnerability": "yes" if stage.supports_vulnerability else "no",
            "repair_needed": "yes" if stage.repair_needed else "no",
            "behavior_hint": self.behavior_hint(stage.stage),
            "recent_shared_events": list(stage.recent_shared_events[:3]),
        }

    @staticmethod
    def behavior_hint(stage: str) -> str:
        hints = {
            "unfamiliar": "Use stronger boundaries, cite memory conservatively, and avoid proactive intimacy.",
            "trust_building": "Use supportive but cautious familiarity; reference stable memory with light confirmation.",
            "stable_companion": "Reference long-term continuity naturally while keeping commitments bounded.",
            "vulnerable_support": "Prioritize support, grounding, and conservative suggestions without expanding promises.",
            "repair_and_recovery": "Acknowledge uncertainty, reduce assertive memory claims, and avoid overfamiliar language.",
        }
        return hints.get(stage, hints["unfamiliar"])

    async def _submit_style_adjustments(
        self,
        user_id: str,
        stage: RelationshipStageState,
        *,
        event_id: str | None = None,
    ) -> None:
        if self.candidate_manager is None or self.personality_evolver is None:
            return
        deltas = self._style_deltas_for_stage(stage.stage)
        if not deltas:
            return
        applicable: list[EvolutionCandidate] = []
        for field_name, delta in deltas.items():
            submission = await self.candidate_manager.submit(
                user_id=user_id,
                affected_area="relationship_style",
                dedupe_key=f"relationship_stage_style:{stage.stage}:{field_name}",
                proposed_change={"kind": "relationship_style", "field": field_name, "delta": delta},
                evidence_summary=f"Relationship stage {stage.stage} suggests {field_name} adjustment.",
                rationale="Stage-aware relationship style nudges remain bounded and candidate-driven.",
                risk_level="low",
                source_event_id=event_id,
                source_context_id=event_id or stage.stage,
                metadata={"owner": "relationship_state_machine", "relationship_stage": stage.stage},
            )
            if submission.action == "apply":
                applicable.append(submission.candidate)
        if applicable:
            await self.personality_evolver.apply_candidates(user_id, applicable, event_id=event_id)

    async def _apply_stage_candidate(
        self,
        user_id: str,
        proposed_change: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> None:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        data = dict(proposed_change.get("relationship_stage", {}))
        relationship_stage = RelationshipStageState(
            stage=str(data.get("stage", "unfamiliar")),
            confidence=float(data.get("confidence", 0.0)),
            updated_at=str(data.get("updated_at", "")) or utc_now_iso(),
            entered_at=str(data.get("entered_at", "")) or utc_now_iso(),
            supports_vulnerability=bool(data.get("supports_vulnerability", False)),
            repair_needed=bool(data.get("repair_needed", False)),
            recent_transition_reason=str(data.get("recent_transition_reason", "")),
            recent_shared_events=list(data.get("recent_shared_events", [])),
        )
        current.world_model.relationship_stage = relationship_stage
        await self.core_memory_scheduler.write(user_id, "world_model", current.world_model, event_id=event_id)
        if self.evolution_journal is not None:
            await self.evolution_journal.record(
                EvolutionEntry(
                    user_id=user_id,
                    event_type="relationship_stage_transition_applied",
                    summary=f"Relationship stage -> {relationship_stage.stage}",
                    details={
                        "relationship_stage_from": proposed_change.get("from_stage"),
                        "relationship_stage_to": relationship_stage.stage,
                        "transition_reason": relationship_stage.recent_transition_reason,
                    },
                )
            )

    def _derive_stage(
        self,
        core_memory: CoreMemory,
        observation: dict[str, Any] | None,
    ) -> RelationshipStageState:
        world_model = core_memory.world_model
        previous = world_model.relationship_stage
        positive_count = self._positive_relationship_signal_count(core_memory)
        stable_preference_count = self._stable_preference_signal_count(core_memory)
        repair_signal = self._has_repair_signal(core_memory, observation)
        vulnerability_signal = self._has_vulnerability_signal(observation)
        stage = "unfamiliar"
        confidence = 0.2 if positive_count else 0.0
        supports_vulnerability = False
        repair_needed = False
        transition_reason = previous.recent_transition_reason

        if repair_signal:
            stage = "repair_and_recovery"
            confidence = 0.9
            repair_needed = True
            transition_reason = "Recent repair or rupture signal detected."
        elif previous.stage == "repair_and_recovery" and positive_count >= 4 and stable_preference_count >= 1:
            stage = "trust_building" if positive_count < 6 else "stable_companion"
            confidence = 0.75 if stage == "trust_building" else 0.82
            transition_reason = "Repair signals eased and steady positive evidence returned."
        elif (
            previous.stage in {"trust_building", "stable_companion", "vulnerable_support"}
            and positive_count >= 4
            and stable_preference_count >= 1
            and not world_model.memory_conflicts
        ):
            stage = "stable_companion"
            confidence = 0.85
            transition_reason = "Stable preferences and repeated positive relationship evidence accumulated."
        elif positive_count >= 2 or stable_preference_count >= 1:
            stage = "trust_building"
            confidence = 0.6
            transition_reason = "Multiple stable relationship signals suggest trust is building."

        if vulnerability_signal and stage in {"trust_building", "stable_companion"}:
            stage = "vulnerable_support"
            confidence = max(confidence, 0.78)
            supports_vulnerability = True
            transition_reason = "High-vulnerability support context appeared on top of an existing trust base."
        elif stage == "stable_companion":
            supports_vulnerability = True

        entered_at = previous.entered_at if previous.stage == stage else utc_now_iso()
        recent_events = self._recent_shared_events(core_memory, observation)
        return RelationshipStageState(
            stage=stage,
            confidence=confidence,
            updated_at=utc_now_iso(),
            entered_at=entered_at,
            supports_vulnerability=supports_vulnerability,
            repair_needed=repair_needed,
            recent_transition_reason=transition_reason,
            recent_shared_events=recent_events,
        )

    @staticmethod
    def _stage_snapshot_equal(left: RelationshipStageState, right: RelationshipStageState) -> bool:
        return (
            left.stage == right.stage
            and abs(left.confidence - right.confidence) < 0.01
            and left.supports_vulnerability == right.supports_vulnerability
            and left.repair_needed == right.repair_needed
            and left.recent_transition_reason == right.recent_transition_reason
            and list(left.recent_shared_events[:3]) == list(right.recent_shared_events[:3])
        )

    @staticmethod
    def _stage_risk(previous: str, new_stage: str) -> str:
        if new_stage == "repair_and_recovery":
            return "medium"
        if previous == "unfamiliar" and new_stage == "stable_companion":
            return "high"
        return "low"

    @staticmethod
    def _style_deltas_for_stage(stage: str) -> dict[str, float]:
        if stage == "unfamiliar":
            return {"boundary_strength": 0.04}
        if stage == "stable_companion":
            return {"warmth": 0.04, "supportiveness": 0.04}
        if stage == "repair_and_recovery":
            return {"boundary_strength": 0.06, "warmth": -0.04}
        return {}

    @staticmethod
    def _positive_relationship_signal_count(core_memory: CoreMemory) -> int:
        count = 0
        for item in core_memory.world_model.relationship_history:
            if item.status in {"active", "superseded"} and item.confidence >= 0.7:
                count += 1
        for item in core_memory.world_model.confirmed_facts + core_memory.world_model.inferred_memories:
            if str(item.memory_key).startswith("support_preference:") and item.status == "active":
                count += 1
        return count

    @staticmethod
    def _stable_preference_signal_count(core_memory: CoreMemory) -> int:
        return sum(
            1
            for item in core_memory.world_model.confirmed_facts + core_memory.world_model.inferred_memories
            if str(item.memory_key).startswith("support_preference:")
            and item.confidence >= 0.75
            and item.status == "active"
        )

    @staticmethod
    def _has_vulnerability_signal(observation: dict[str, Any] | None) -> bool:
        if not observation:
            return False
        text = " ".join(
            [
                str(observation.get("summary", "")),
                str(observation.get("lesson_text", "")),
                str(observation.get("content", "")),
            ]
        ).lower()
        if observation.get("emotional_risk") in {"medium", "high"}:
            return True
        tokens = ("overwhelmed", "anxious", "sad", "lonely", "can't go on", "support")
        return any(token in text for token in tokens)

    @staticmethod
    def _has_repair_signal(core_memory: CoreMemory, observation: dict[str, Any] | None) -> bool:
        if core_memory.world_model.memory_conflicts:
            for item in core_memory.world_model.memory_conflicts:
                text = f"{item.content} {item.memory_key}".lower()
                if any(token in text for token in ("misunder", "boundary", "hurt", "rupture", "repair")):
                    return True
        if not observation:
            return False
        text = " ".join(
            [
                str(observation.get("summary", "")),
                str(observation.get("lesson_text", "")),
                str(observation.get("content", "")),
            ]
        ).lower()
        return any(token in text for token in ("misunderstood", "you were wrong", "boundary", "hurt", "repair"))

    @staticmethod
    def _recent_shared_events(core_memory: CoreMemory, observation: dict[str, Any] | None) -> list[str]:
        events: list[str] = []
        source_items = (
            list(core_memory.world_model.relationship_history)
            + list(core_memory.world_model.confirmed_facts)
            + list(core_memory.world_model.inferred_memories)
            + list(core_memory.world_model.memory_conflicts)
        )
        for item in sorted(source_items, key=lambda value: str(getattr(value, "updated_at", "")), reverse=True):
            content = str(getattr(item, "content", "")).strip()
            if not content:
                continue
            if str(getattr(item, "memory_key", "")).startswith("support_preference:") or getattr(item, "truth_type", "") == "relationship":
                events.append(content)
            if len(events) >= 3:
                break
        if observation:
            content = str(observation.get("summary") or observation.get("lesson_text") or "").strip()
            if content and content not in events:
                events.insert(0, content)
        return events[:3]
