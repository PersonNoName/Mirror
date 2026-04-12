"""User-visible governance over durable world-model memory."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.memory.core_memory import (
    DurableMemory,
    FactualMemory,
    MemoryGovernancePolicy,
    RelationshipMemory,
    WorldModel,
    utc_now_iso,
)


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class MemoryGovernanceService:
    """Coordinate user-visible memory inspection and governance operations."""

    def __init__(
        self,
        *,
        core_memory_cache: Any,
        core_memory_scheduler: Any,
        graph_store: Any | None,
        candidate_manager: Any | None,
        evolution_journal: Any | None,
    ) -> None:
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.graph_store = graph_store
        self.candidate_manager = candidate_manager
        self.evolution_journal = evolution_journal
        self.degraded = False

    async def list_memory(
        self,
        *,
        user_id: str,
        include_candidates: bool = True,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = self.prune_world_model(current.world_model)
        items: list[dict[str, Any]] = []
        for section in (
            world_model.confirmed_facts,
            world_model.inferred_memories,
            world_model.relationship_history,
            world_model.pending_confirmations,
            world_model.memory_conflicts,
        ):
            for item in section:
                if not include_superseded and (
                    item.status == "superseded" or item.metadata.get("deleted_by_user", False)
                ):
                    continue
                items.append(self._serialize_memory_item(item, visibility="durable"))
        if include_candidates and self.candidate_manager is not None:
            for candidate in self.candidate_manager.list_candidates(
                user_id=user_id,
                affected_area="world_model",
                statuses={"candidate", "pending"},
            ):
                if self._candidate_expired(world_model.memory_governance, candidate):
                    continue
                proposed = dict(candidate.proposed_change.get("memory", {}))
                if not proposed:
                    continue
                items.append(
                    {
                        "memory_key": str(proposed.get("memory_key", "")),
                        "content": str(proposed.get("content", "")),
                        "truth_type": str(proposed.get("truth_type", "fact")),
                        "status": str(candidate.status),
                        "source": str(proposed.get("source", "candidate_pipeline")),
                        "confidence": float(proposed.get("confidence", 0.0)),
                        "confirmed_by_user": bool(proposed.get("confirmed_by_user", False)),
                        "updated_at": str(proposed.get("updated_at", candidate.created_at)),
                        "visibility": "candidate",
                    }
                )
        return sorted(items, key=lambda item: str(item.get("updated_at", "")), reverse=True)

    async def get_policy(self, user_id: str) -> MemoryGovernancePolicy:
        current = await self.core_memory_cache.get(user_id)
        return deepcopy(current.world_model.memory_governance)

    async def set_blocked(
        self,
        *,
        user_id: str,
        content_class: str,
        blocked: bool,
    ) -> MemoryGovernancePolicy:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        blocked_classes = set(world_model.memory_governance.blocked_content_classes)
        if blocked:
            blocked_classes.add(content_class)
        else:
            blocked_classes.discard(content_class)
        world_model.memory_governance.blocked_content_classes = sorted(blocked_classes)
        world_model.memory_governance.updated_at = utc_now_iso()
        rollback_ids = (
            await self._revert_candidates_for_class(user_id, content_class, rollback_reason="governance_blocked")
            if blocked
            else []
        )
        await self.core_memory_scheduler.write(user_id, "world_model", world_model)
        await self._record(
            user_id=user_id,
            event_type="memory_governance_block_updated",
            summary=f"Updated governance block for {content_class}",
            details={
                "content_class": content_class,
                "blocked": blocked,
                "governance_action": "block_update",
                "rollback_candidate_ids": rollback_ids,
            },
        )
        return deepcopy(world_model.memory_governance)

    async def correct_memory(
        self,
        *,
        user_id: str,
        memory_key: str,
        corrected_content: str,
        truth_type: str,
        subject: str | None = None,
        relation: str | None = None,
        object: str | None = None,
    ) -> dict[str, Any]:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        matches = self._find_memories(world_model, memory_key)
        active_matches = [
            item for item in matches if item.status != "superseded" and not item.metadata.get("deleted_by_user", False)
        ]
        if not active_matches:
            raise KeyError(memory_key)
        target = active_matches[-1]
        for item in active_matches:
            item.status = "superseded"
            item.metadata["corrected_by_user"] = True
        replacement = self._build_corrected_memory(
            target=target,
            corrected_content=corrected_content,
            truth_type=truth_type,
            subject=subject,
            relation=relation,
            object=object,
        )
        self._append_memory(world_model, replacement)
        if isinstance(target, RelationshipMemory) and self.graph_store is not None:
            await self.graph_store.supersede_relation(
                user_id=user_id,
                subject=target.subject,
                relation=target.relation,
                object=target.object,
                reason="governance_corrected",
            )
        if isinstance(replacement, RelationshipMemory) and self.graph_store is not None:
            await self.graph_store.upsert_relation(
                user_id=user_id,
                subject=replacement.subject,
                relation=replacement.relation,
                object=replacement.object,
                confidence=replacement.confidence,
                source=replacement.source,
                confirmed_by_user=True,
                status=replacement.status,
                time_horizon=replacement.time_horizon,
                sensitivity=replacement.sensitivity,
                conflict_with=replacement.conflict_with,
                metadata=dict(replacement.metadata),
            )
        rollback_ids = await self._revert_candidates_for_memory_key(
            user_id,
            memory_key,
            rollback_reason="governance_corrected",
        )
        await self.core_memory_scheduler.write(user_id, "world_model", world_model)
        await self._record(
            user_id=user_id,
            event_type="memory_governance_corrected",
            summary=f"Corrected memory {memory_key}",
            details={
                "memory_key": memory_key,
                "truth_type": truth_type,
                "visibility": "durable",
                "content_class": self.content_class_for_memory(replacement),
                "governance_action": "correct",
                "replacement_memory_key": replacement.memory_key,
                "rollback_candidate_ids": rollback_ids,
            },
        )
        return self._serialize_memory_item(replacement, visibility="durable")

    async def delete_memory(self, *, user_id: str, memory_key: str, reason: str) -> None:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        matches = self._find_memories(world_model, memory_key)
        active_matches = [
            item for item in matches if item.status != "superseded" and not item.metadata.get("deleted_by_user", False)
        ]
        if not active_matches:
            raise KeyError(memory_key)
        target = active_matches[-1]
        for item in active_matches:
            item.status = "superseded"
            item.metadata["deleted_by_user"] = True
            item.metadata["governance_reason"] = reason
        if isinstance(target, RelationshipMemory) and self.graph_store is not None:
            await self.graph_store.supersede_relation(
                user_id=user_id,
                subject=target.subject,
                relation=target.relation,
                object=target.object,
                reason=reason,
            )
        rollback_ids = await self._revert_candidates_for_memory_key(
            user_id,
            memory_key,
            rollback_reason="governance_deleted",
        )
        await self.core_memory_scheduler.write(user_id, "world_model", world_model)
        await self._record(
            user_id=user_id,
            event_type="memory_governance_deleted",
            summary=f"Deleted memory {memory_key}",
            details={
                "memory_key": memory_key,
                "truth_type": target.truth_type,
                "visibility": "durable",
                "content_class": self.content_class_for_memory(target),
                "governance_action": "delete",
                "rollback_candidate_ids": rollback_ids,
            },
        )

    def is_blocked(self, world_model: WorldModel, content_class: str) -> bool:
        return content_class in set(world_model.memory_governance.blocked_content_classes)

    def prune_world_model(self, world_model: WorldModel) -> WorldModel:
        retention = world_model.memory_governance.retention_days
        clone = deepcopy(world_model)
        clone.inferred_memories = self._filter_by_retention(
            [item for item in clone.inferred_memories if item.status != "superseded"],
            retention.get("inference", 30),
        )
        clone.pending_confirmations = self._filter_by_retention(
            [item for item in clone.pending_confirmations if not item.metadata.get("deleted_by_user", False)],
            retention.get("pending_confirmation", 7),
        )
        clone.memory_conflicts = self._filter_by_retention(
            [item for item in clone.memory_conflicts if not item.metadata.get("deleted_by_user", False)],
            retention.get("memory_conflicts", 30),
        )
        clone.confirmed_facts = [
            item
            for item in clone.confirmed_facts
            if not item.metadata.get("deleted_by_user", False) and item.status != "superseded"
        ]
        clone.relationship_history = [
            item
            for item in clone.relationship_history
            if not item.metadata.get("deleted_by_user", False) and item.status != "superseded"
        ]
        return clone

    async def prune_and_record(self, *, user_id: str, world_model: WorldModel) -> WorldModel:
        before = self._count_governable_items(world_model)
        pruned = self.prune_world_model(world_model)
        after = self._count_governable_items(pruned)
        if before != after:
            await self._record(
                user_id=user_id,
                event_type="memory_governance_pruned",
                summary="Pruned expired user-governed memory entries.",
                details={
                    "governance_action": "prune",
                    "pruned_count": before - after,
                    "visibility": "durable",
                },
            )
        return pruned

    @staticmethod
    def content_class_for_memory(memory: DurableMemory) -> str:
        if memory.memory_key.startswith("support_preference:"):
            return "support_preference"
        if memory.truth_type == "relationship":
            return "relationship"
        if memory.truth_type == "inference":
            return "inference"
        return "fact"

    @staticmethod
    def _serialize_memory_item(item: DurableMemory, *, visibility: str) -> dict[str, Any]:
        return {
            "memory_key": item.memory_key,
            "content": item.content,
            "truth_type": item.truth_type,
            "status": item.status,
            "source": item.source,
            "confidence": item.confidence,
            "confirmed_by_user": item.confirmed_by_user,
            "updated_at": item.updated_at,
            "visibility": visibility,
        }

    @staticmethod
    def _filter_by_retention(items: list[DurableMemory], retention_days: int) -> list[DurableMemory]:
        if retention_days <= 0:
            return list(items)
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        kept: list[DurableMemory] = []
        for item in items:
            updated_at = _parse_iso(item.updated_at)
            if updated_at is None or updated_at >= cutoff:
                kept.append(item)
        return kept

    @staticmethod
    def _count_governable_items(world_model: WorldModel) -> int:
        return sum(
            len(section)
            for section in (
                world_model.confirmed_facts,
                world_model.inferred_memories,
                world_model.relationship_history,
                world_model.pending_confirmations,
                world_model.memory_conflicts,
            )
        )

    @staticmethod
    def _find_memory(world_model: WorldModel, memory_key: str) -> DurableMemory | None:
        matches = MemoryGovernanceService._find_memories(world_model, memory_key)
        return matches[-1] if matches else None

    @staticmethod
    def _find_memories(world_model: WorldModel, memory_key: str) -> list[DurableMemory]:
        matches: list[DurableMemory] = []
        for section in (
            world_model.confirmed_facts,
            world_model.inferred_memories,
            world_model.relationship_history,
            world_model.pending_confirmations,
            world_model.memory_conflicts,
        ):
            for item in section:
                if item.memory_key == memory_key:
                    matches.append(item)
        return matches

    @staticmethod
    def _append_memory(world_model: WorldModel, memory: DurableMemory) -> None:
        if isinstance(memory, RelationshipMemory):
            world_model.relationship_history.append(memory)
        else:
            world_model.confirmed_facts.append(memory)

    @staticmethod
    def _build_corrected_memory(
        *,
        target: DurableMemory,
        corrected_content: str,
        truth_type: str,
        subject: str | None,
        relation: str | None,
        object: str | None,
    ) -> DurableMemory:
        metadata = dict(target.metadata)
        metadata["corrected_from"] = target.memory_key
        if truth_type == "relationship" or isinstance(target, RelationshipMemory):
            relation_item = target if isinstance(target, RelationshipMemory) else None
            subject_value = subject or (relation_item.subject if relation_item else "")
            relation_value = relation or (relation_item.relation if relation_item else "")
            object_value = object or (relation_item.object if relation_item else "")
            return RelationshipMemory(
                content=corrected_content,
                source="user_correction",
                confidence=1.0,
                updated_at=utc_now_iso(),
                confirmed_by_user=True,
                truth_type="relationship",
                time_horizon="long_term",
                status="active",
                sensitivity=target.sensitivity,
                memory_key=f"relationship:{subject_value}:{relation_value}:{object_value}",
                metadata=metadata,
                subject=subject_value,
                relation=relation_value,
                object=object_value,
            )
        return FactualMemory(
            content=corrected_content,
            source="user_correction",
            confidence=1.0,
            updated_at=utc_now_iso(),
            confirmed_by_user=True,
            truth_type="fact",
            time_horizon="long_term",
            status="active",
            sensitivity=target.sensitivity,
            memory_key=target.memory_key.replace("inference:", "fact:", 1),
            metadata=metadata,
        )

    async def _revert_candidates_for_memory_key(
        self,
        user_id: str,
        memory_key: str,
        *,
        rollback_reason: str,
    ) -> list[str]:
        if self.candidate_manager is None:
            return []
        reverted: list[str] = []
        for candidate in self.candidate_manager.list_candidates(
            user_id=user_id,
            affected_area="world_model",
            statuses={"candidate", "pending"},
        ):
            proposed = dict(candidate.proposed_change.get("memory", {}))
            if proposed.get("memory_key") != memory_key:
                continue
            await self.candidate_manager.mark_reverted(candidate.id, rollback_reason)
            reverted.append(candidate.id)
        return reverted

    async def _revert_candidates_for_class(
        self,
        user_id: str,
        content_class: str,
        *,
        rollback_reason: str,
    ) -> list[str]:
        if self.candidate_manager is None:
            return []
        reverted: list[str] = []
        for candidate in self.candidate_manager.list_candidates(
            user_id=user_id,
            affected_area="world_model",
            statuses={"candidate", "pending"},
        ):
            proposed = dict(candidate.proposed_change.get("memory", {}))
            proposed_class = self.content_class_for_candidate(candidate)
            if proposed_class != content_class:
                continue
            await self.candidate_manager.mark_reverted(candidate.id, rollback_reason)
            reverted.append(candidate.id)
        return reverted

    @classmethod
    def content_class_for_candidate(cls, candidate: Any) -> str:
        proposed = dict(candidate.proposed_change.get("memory", {}))
        memory_key = str(proposed.get("memory_key", ""))
        truth_type = str(proposed.get("truth_type", "fact"))
        if memory_key.startswith("support_preference:"):
            return "support_preference"
        if truth_type == "relationship":
            return "relationship"
        if truth_type == "inference":
            return "inference"
        return "fact"

    @staticmethod
    def _candidate_expired(policy: MemoryGovernancePolicy, candidate: Any) -> bool:
        retention_days = int(policy.retention_days.get("candidate", 7))
        if retention_days <= 0:
            return False
        created_at = _parse_iso(str(candidate.created_at))
        if created_at is None:
            return False
        return created_at < (datetime.now(timezone.utc) - timedelta(days=retention_days))

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
        from app.evolution.event_bus import EvolutionEntry

        await self.evolution_journal.record(
            EvolutionEntry(
                user_id=user_id,
                event_type=event_type,
                summary=summary,
                details=details,
            )
        )
