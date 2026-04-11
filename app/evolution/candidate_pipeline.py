"""In-memory controlled evolution candidate pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from app.evolution.event_bus import EvolutionEntry
from app.memory.core_memory import utc_now_iso


EvolutionCandidateStatus = Literal["candidate", "pending", "applied", "reverted"]
EvolutionRiskLevel = Literal["low", "medium", "high"]
EvolutionAffectedArea = Literal["self_cognition", "world_model", "personality", "relationship_style"]
EvolutionPipelineAction = Literal["hold", "apply", "hitl"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class EvolutionCandidate:
    """Aggregated evolution proposal tracked before long-term application."""

    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    affected_area: EvolutionAffectedArea = "world_model"
    proposed_change: dict[str, Any] = field(default_factory=dict)
    evidence_summary: str = ""
    evidence_count: int = 1
    rationale: str = ""
    risk_level: EvolutionRiskLevel = "low"
    status: EvolutionCandidateStatus = "candidate"
    source_event_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now_iso)
    applied_at: str | None = None
    reverted_at: str | None = None
    dedupe_key: str = ""
    source_context_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvolutionSubmissionResult:
    """Decision returned after candidate aggregation and policy evaluation."""

    candidate: EvolutionCandidate
    action: EvolutionPipelineAction
    created: bool = False


class EvolutionCandidateManager:
    """Coordinate candidate lifecycle, aggregation, and policy decisions."""

    LOW_RISK_THRESHOLD = 2
    MEDIUM_RISK_THRESHOLD = 3
    MEDIUM_RISK_MIN_CONTEXTS = 2
    RECENT_REVERT_WINDOW_HOURS = 24

    def __init__(self, evolution_journal: Any | None = None) -> None:
        self.evolution_journal = evolution_journal
        self._candidates_by_id: dict[str, EvolutionCandidate] = {}
        self._thread_index: dict[tuple[str, str, str], str] = {}
        self.degraded = False

    async def submit(
        self,
        *,
        user_id: str,
        affected_area: EvolutionAffectedArea,
        dedupe_key: str,
        proposed_change: dict[str, Any],
        evidence_summary: str,
        rationale: str,
        risk_level: EvolutionRiskLevel,
        source_event_id: str | None = None,
        source_context_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvolutionSubmissionResult:
        thread_key = (user_id, affected_area, dedupe_key)
        created = False
        candidate = self._candidate_for_thread(thread_key)
        if candidate is None:
            candidate = EvolutionCandidate(
                user_id=user_id,
                affected_area=affected_area,
                proposed_change=dict(proposed_change),
                evidence_summary=evidence_summary,
                rationale=rationale,
                risk_level=risk_level,
                dedupe_key=dedupe_key,
                metadata=dict(metadata or {}),
            )
            self._candidates_by_id[candidate.id] = candidate
            self._thread_index[thread_key] = candidate.id
            created = True
            if source_event_id:
                candidate.source_event_ids.append(source_event_id)
            if source_context_id:
                candidate.source_context_ids.append(source_context_id)
            await self._record(
                "evolution_candidate_created",
                candidate,
                summary=evidence_summary,
            )
        else:
            candidate.proposed_change = dict(proposed_change)
            candidate.evidence_summary = evidence_summary
            candidate.rationale = rationale
            candidate.risk_level = self._max_risk(candidate.risk_level, risk_level)
            candidate.metadata.update(dict(metadata or {}))
            if source_event_id and source_event_id not in candidate.source_event_ids:
                candidate.source_event_ids.append(source_event_id)
                candidate.evidence_count += 1
            elif source_event_id is None:
                candidate.evidence_count += 1
            if source_context_id and source_context_id not in candidate.source_context_ids:
                candidate.source_context_ids.append(source_context_id)
            await self._record(
                "evolution_candidate_updated",
                candidate,
                summary=evidence_summary,
            )

        desired_status = self._desired_status(candidate)
        if desired_status == "pending" and candidate.status != "pending":
            candidate.status = "pending"
            await self._record(
                "evolution_candidate_pending",
                candidate,
                summary=f"Pending candidate for {candidate.affected_area}",
            )
        elif desired_status == "candidate" and candidate.status == "reverted":
            candidate.status = "candidate"

        return EvolutionSubmissionResult(
            candidate=candidate,
            action=self._action_for(candidate),
            created=created,
        )

    def get_candidate(self, candidate_id: str) -> EvolutionCandidate | None:
        return self._candidates_by_id.get(candidate_id)

    def list_candidates(
        self,
        *,
        user_id: str | None = None,
        affected_area: EvolutionAffectedArea | None = None,
        statuses: set[EvolutionCandidateStatus] | None = None,
    ) -> list[EvolutionCandidate]:
        items = list(self._candidates_by_id.values())
        if user_id is not None:
            items = [item for item in items if item.user_id == user_id]
        if affected_area is not None:
            items = [item for item in items if item.affected_area == affected_area]
        if statuses is not None:
            items = [item for item in items if item.status in statuses]
        return list(items)

    async def mark_applied(self, candidate_id: str) -> EvolutionCandidate | None:
        candidate = self._candidates_by_id.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = "applied"
        candidate.applied_at = utc_now_iso()
        await self._record(
            "evolution_candidate_applied",
            candidate,
            summary=f"Applied candidate for {candidate.affected_area}",
        )
        return candidate

    async def mark_reverted(self, candidate_id: str, rollback_reason: str) -> EvolutionCandidate | None:
        candidate = self._candidates_by_id.get(candidate_id)
        if candidate is None:
            return None
        candidate.status = "reverted"
        candidate.reverted_at = utc_now_iso()
        candidate.metadata["rollback_reason"] = rollback_reason
        await self._record(
            "evolution_candidate_reverted",
            candidate,
            summary=f"Reverted candidate for {candidate.affected_area}",
        )
        return candidate

    def attach_hitl_task(self, candidate_id: str, task_id: str) -> None:
        candidate = self._candidates_by_id.get(candidate_id)
        if candidate is None:
            return
        candidate.metadata["hitl_task_id"] = task_id

    def pending_count(self) -> int:
        return sum(1 for item in self._candidates_by_id.values() if item.status == "pending")

    def high_risk_pending_count(self) -> int:
        return sum(
            1
            for item in self._candidates_by_id.values()
            if item.status == "pending" and item.risk_level == "high"
        )

    def recent_reverted_count(self) -> int:
        cutoff = _utc_now() - timedelta(hours=self.RECENT_REVERT_WINDOW_HOURS)
        total = 0
        for item in self._candidates_by_id.values():
            if item.status != "reverted" or item.reverted_at is None:
                continue
            try:
                reverted_at = datetime.fromisoformat(item.reverted_at)
            except ValueError:
                continue
            if reverted_at >= cutoff:
                total += 1
        return total

    def summary(self) -> dict[str, Any]:
        return {
            "pending_candidate_count": self.pending_count(),
            "high_risk_pending_count": self.high_risk_pending_count(),
            "recent_reverted_count": self.recent_reverted_count(),
            "degraded": self.degraded,
        }

    def _candidate_for_thread(self, thread_key: tuple[str, str, str]) -> EvolutionCandidate | None:
        candidate_id = self._thread_index.get(thread_key)
        if not candidate_id:
            return None
        candidate = self._candidates_by_id.get(candidate_id)
        if candidate is None or candidate.status in {"applied", "reverted"}:
            return None
        return candidate

    @classmethod
    def _desired_status(cls, candidate: EvolutionCandidate) -> EvolutionCandidateStatus:
        if candidate.risk_level == "low":
            return "candidate"
        return "pending"

    @classmethod
    def _action_for(cls, candidate: EvolutionCandidate) -> EvolutionPipelineAction:
        if candidate.risk_level == "high":
            return "hitl"
        if candidate.risk_level == "medium":
            if (
                candidate.evidence_count >= cls.MEDIUM_RISK_THRESHOLD
                and len(candidate.source_context_ids) >= cls.MEDIUM_RISK_MIN_CONTEXTS
            ):
                return "apply"
            return "hold"
        if candidate.evidence_count >= cls.LOW_RISK_THRESHOLD:
            return "apply"
        return "hold"

    @staticmethod
    def _max_risk(left: EvolutionRiskLevel, right: EvolutionRiskLevel) -> EvolutionRiskLevel:
        ordering = {"low": 0, "medium": 1, "high": 2}
        return left if ordering[left] >= ordering[right] else right

    async def _record(self, event_type: str, candidate: EvolutionCandidate, *, summary: str) -> None:
        if self.evolution_journal is None:
            return
        await self.evolution_journal.record(
            EvolutionEntry(
                user_id=candidate.user_id,
                event_type=event_type,
                summary=summary,
                details={
                    "candidate_id": candidate.id,
                    "candidate_status": candidate.status,
                    "risk_level": candidate.risk_level,
                    "affected_area": candidate.affected_area,
                    "evidence_count": candidate.evidence_count,
                    "dedupe_key": candidate.dedupe_key,
                    "proposed_change": dict(candidate.proposed_change),
                    "rollback_reason": candidate.metadata.get("rollback_reason"),
                    "relationship_stage_from": candidate.metadata.get("relationship_stage_from"),
                    "relationship_stage_to": candidate.metadata.get("relationship_stage_to"),
                    "transition_reason": candidate.metadata.get("transition_reason"),
                },
            )
        )
