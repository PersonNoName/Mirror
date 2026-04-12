"""Cognition updater for lessons."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.evolution.candidate_pipeline import (
    EvolutionCandidate,
    EvolutionCandidateManager,
)
from app.memory.core_memory import (
    AgentContinuityState,
    AgentEmotionalState,
    DurableMemory,
    FactualMemory,
    InferredMemory,
    RelationshipMemory,
    SharedExperience,
    TopicAffinity,
    UserEmotionalState,
    utc_now_iso,
)
from app.platform.base import HitlRequest
from app.tasks.models import (
    EvolutionCandidateRequest,
    Lesson,
    MemoryConfirmationRequest,
    Task,
)


class CognitionUpdater:
    """Update self-cognition or world-model based on lessons."""

    def __init__(
        self,
        *,
        core_memory_cache: Any,
        core_memory_scheduler: Any,
        graph_store: Any | None,
        task_store: Any | None = None,
        blackboard: Any | None = None,
        candidate_manager: EvolutionCandidateManager | None = None,
        relationship_state_machine: Any | None = None,
        memory_governance_service: Any | None = None,
        mid_term_memory_store: Any | None = None,
    ) -> None:
        self.core_memory_cache = core_memory_cache
        self.core_memory_scheduler = core_memory_scheduler
        self.graph_store = graph_store
        self.task_store = task_store
        self.blackboard = blackboard
        self.candidate_manager = candidate_manager
        self.relationship_state_machine = relationship_state_machine
        self.memory_governance_service = memory_governance_service
        self.mid_term_memory_store = mid_term_memory_store
        self._last_updated: dict[str, datetime] = {}

    async def handle_lesson_generated(self, event: Any) -> None:
        lesson = Lesson(**event.payload["lesson"])
        if not self._should_run(lesson.user_id):
            return
        if lesson.is_agent_capability_issue:
            await self._update_self_cognition(lesson)
        else:
            await self._update_world_model(lesson)
        self._last_updated[lesson.user_id] = datetime.now(timezone.utc)

    async def handle_hitl_feedback(self, event: Any) -> None:
        if self.task_store is None:
            return
        task_id = str(event.payload.get("task_id", ""))
        if not task_id:
            return
        task = await self.task_store.get(task_id)
        if task is None:
            return
        confirmation = dict(task.metadata.get("memory_confirmation", {}))
        if confirmation:
            await self._handle_memory_confirmation_feedback(task, confirmation, event)
            return
        evolution_metadata = dict(task.metadata.get("evolution_candidate", {}))
        if not evolution_metadata:
            return
        await self._handle_evolution_feedback(task, evolution_metadata, event)

    async def _handle_memory_confirmation_feedback(
        self,
        task: Task,
        confirmation: dict[str, Any],
        event: Any,
    ) -> None:
        decision = str(event.payload.get("decision", ""))
        user_id = str(task.metadata.get("user_id", ""))
        if not user_id:
            return

        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        memory_key = str(confirmation.get("memory_key", ""))
        pending = [
            item
            for item in world_model.pending_confirmations
            if item.memory_key != memory_key
        ]
        candidate = self._memory_from_dict(dict(confirmation.get("candidate", {})))
        if candidate is None:
            world_model.pending_confirmations = pending
            await self.core_memory_scheduler.write(
                user_id, "world_model", world_model, event_id=task.id
            )
            if self.relationship_state_machine is not None:
                await self.relationship_state_machine.evaluate(
                    user_id=user_id, event_id=task.id
                )
            return

        if decision == "approve":
            candidate.confirmed_by_user = True
            candidate.status = "active"
            if isinstance(candidate, FactualMemory):
                world_model.confirmed_facts = self._merge_memory(
                    world_model.confirmed_facts, candidate
                )
            elif isinstance(candidate, InferredMemory):
                world_model.inferred_memories = self._merge_memory(
                    world_model.inferred_memories, candidate
                )
            elif isinstance(candidate, RelationshipMemory):
                await self._promote_relationship(user_id, candidate)
            await self._mark_mid_term_item_promoted(user_id, candidate)
            task.status = "done"
        elif decision == "reject":
            candidate.status = "superseded"
            world_model.memory_conflicts = self._merge_memory(
                world_model.memory_conflicts, candidate
            )
            await self._suppress_mid_term_item(user_id, candidate, reason="memory_confirmation_rejected")
            task.status = "done"
        else:
            pending.append(candidate)
            task.status = "waiting_hitl"

        world_model.pending_confirmations = pending
        await self.core_memory_scheduler.write(
            user_id, "world_model", world_model, event_id=task.id
        )
        if self.relationship_state_machine is not None:
            await self.relationship_state_machine.evaluate(
                user_id=user_id, event_id=task.id
            )
        if self.task_store is not None:
            await self.task_store.update(task)

    async def _handle_evolution_feedback(
        self,
        task: Task,
        evolution_metadata: dict[str, Any],
        event: Any,
    ) -> None:
        if self.candidate_manager is None:
            return
        candidate_id = str(evolution_metadata.get("candidate_id", ""))
        candidate = self.candidate_manager.get_candidate(candidate_id)
        if candidate is None:
            return
        decision = str(event.payload.get("decision", ""))
        user_id = str(task.metadata.get("user_id", "")) or candidate.user_id
        if decision == "approve":
            if candidate.affected_area == "self_cognition":
                await self._apply_self_cognition_candidate(
                    user_id, candidate.proposed_change, event_id=task.id
                )
            elif candidate.affected_area == "world_model":
                await self._apply_world_model_candidate(
                    user_id, candidate.proposed_change, event_id=task.id
                )
            await self.candidate_manager.mark_applied(candidate.id)
            task.status = "done"
        elif decision == "reject":
            memory = self._memory_from_dict(dict(candidate.proposed_change.get("memory", {})))
            if memory is not None:
                await self._suppress_mid_term_item(user_id, memory, reason="evolution_rejected")
            await self.candidate_manager.mark_reverted(candidate.id, "hitl_rejected")
            task.status = "done"
        else:
            task.status = "waiting_hitl"
        if self.task_store is not None:
            await self.task_store.update(task)

    def _should_run(self, user_id: str) -> bool:
        last = self._last_updated.get(user_id)
        if last is None:
            return True
        return (datetime.now(timezone.utc) - last).total_seconds() >= 600

    async def _update_self_cognition(self, lesson: Lesson) -> None:
        proposed_change = {
            "domain": lesson.domain or "general",
            "outcome": lesson.outcome,
            "root_cause": lesson.root_cause,
            "summary": lesson.summary,
        }
        if self.candidate_manager is None:
            await self._apply_self_cognition_candidate(
                lesson.user_id, proposed_change, event_id=lesson.id
            )
            return
        submission = await self.candidate_manager.submit(
            user_id=lesson.user_id,
            affected_area="self_cognition",
            dedupe_key=f"self_cognition:{lesson.domain or 'general'}",
            proposed_change=proposed_change,
            evidence_summary=lesson.summary
            or lesson.root_cause
            or f"Capability signal for {lesson.domain or 'general'}",
            rationale="Capability and limitation updates now require candidate aggregation before long-term write.",
            risk_level="medium"
            if lesson.outcome != "done" or bool(lesson.root_cause)
            else "low",
            source_event_id=lesson.id,
            source_context_id=str(
                lesson.details.get("session_id") or lesson.source_task_id or lesson.id
            ),
            metadata={"source": "lesson"},
        )
        if submission.action == "apply":
            await self._apply_self_cognition_candidate(
                lesson.user_id,
                submission.candidate.proposed_change,
                event_id=lesson.id,
            )
            await self.candidate_manager.mark_applied(submission.candidate.id)
        elif submission.action == "hitl":
            await self._create_evolution_candidate_task(
                lesson.user_id, submission.candidate
            )

    async def _apply_self_cognition_candidate(
        self,
        user_id: str,
        proposed_change: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> None:
        current = await self.core_memory_cache.get(user_id)
        block = current.self_cognition
        domain = str(proposed_change.get("domain") or "general")
        entry = block.capability_map.get(domain)
        if entry is None:
            from app.memory.core_memory import CapabilityEntry

            entry = CapabilityEntry(
                description=f"{domain} capability",
                confidence=0.5 if proposed_change.get("outcome") == "done" else 0.3,
            )
            block.capability_map[domain] = entry
        if proposed_change.get("outcome") == "done":
            entry.confidence = min(1.0, entry.confidence + 0.05)
        else:
            entry.confidence = max(0.0, entry.confidence - 0.1)
            root_cause = str(proposed_change.get("root_cause") or "")
            if root_cause and root_cause not in entry.limitations:
                entry.limitations.append(root_cause)
        if proposed_change.get("root_cause"):
            from app.memory.core_memory import MemoryEntry

            block.known_limits.append(
                MemoryEntry(content=str(proposed_change["root_cause"]))
            )
        block.version += 1
        await self.core_memory_scheduler.write(
            user_id, "self_cognition", block, event_id=event_id
        )

    async def _update_world_model(self, lesson: Lesson) -> None:
        if lesson.domain == "emotional_continuity":
            await self._apply_user_emotional_state(lesson)
            return
        if lesson.domain == "agent_continuity":
            await self._apply_agent_continuity_state(lesson)
            return
        if lesson.domain == "agent_emotional":
            await self._apply_agent_emotional_state(lesson)
            return
        if lesson.domain == "shared_experience":
            await self._apply_shared_experience(lesson)
            return
        candidate = self._classify_memory(lesson)
        if self.memory_governance_service is not None:
            current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
            content_class = self.memory_governance_service.content_class_for_memory(
                candidate
            )
            if self.memory_governance_service.is_blocked(
                current.world_model, content_class
            ):
                if self.candidate_manager is not None:
                    await self.memory_governance_service._revert_candidates_for_class(
                        lesson.user_id,
                        content_class,
                        rollback_reason="governance_blocked",
                    )
                return

        if self._requires_confirmation(candidate):
            current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
            world_model = current.world_model
            candidate.status = "pending_confirmation"
            world_model.pending_confirmations = self._merge_memory(
                world_model.pending_confirmations, candidate
            )
            await self.core_memory_scheduler.write(
                lesson.user_id, "world_model", world_model, event_id=lesson.id
            )
            await self._create_memory_confirmation_task(lesson, candidate)
            return

        current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
        conflict = None
        if isinstance(candidate, InferredMemory):
            conflict = self._detect_conflict(
                current.world_model.confirmed_facts, candidate
            )
            if conflict is not None:
                candidate.status = "conflicted"
                candidate.conflict_with = [conflict.memory_key or conflict.content]

        if self.candidate_manager is None:
            await self._apply_world_model_candidate(
                lesson.user_id,
                {"memory": asdict(candidate)},
                event_id=lesson.id,
            )
            return

        submission = await self.candidate_manager.submit(
            user_id=lesson.user_id,
            affected_area="world_model",
            dedupe_key=self._world_model_dedupe_key(candidate),
            proposed_change={"memory": asdict(candidate)},
            evidence_summary=candidate.content,
            rationale="World-model lessons now flow through the controlled evolution candidate pipeline.",
            risk_level=self._world_model_risk(candidate, conflict),
            source_event_id=lesson.id,
            source_context_id=str(
                lesson.details.get("session_id") or lesson.source_task_id or lesson.id
            ),
            metadata={"owner": "cognition_updater", "truth_type": candidate.truth_type},
        )
        if submission.action == "apply":
            await self._apply_world_model_candidate(
                lesson.user_id,
                submission.candidate.proposed_change,
                event_id=lesson.id,
            )
            await self.candidate_manager.mark_applied(submission.candidate.id)
        elif submission.action == "hitl":
            await self._create_evolution_candidate_task(
                lesson.user_id, submission.candidate
            )
        elif submission.action == "hold" and candidate.confirmed_by_user:
            await self._apply_world_model_candidate(
                lesson.user_id,
                {"memory": asdict(candidate)},
                event_id=lesson.id,
            )
        elif self.relationship_state_machine is not None:
            await self.relationship_state_machine.evaluate(
                user_id=lesson.user_id,
                observation=self._relationship_observation(lesson),
                event_id=lesson.id,
            )

    async def _apply_user_emotional_state(self, lesson: Lesson) -> None:
        current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
        previous = current.user_emotional_state
        details = dict(lesson.details)
        if lesson.category == "emotional_resolution":
            # Grace period: keep a faint trace for 24h so the next session
            # can still gently reference "you mentioned you were feeling better".
            now = datetime.now(timezone.utc)
            grace_until = (now + timedelta(hours=24)).isoformat()
            current.user_emotional_state = UserEmotionalState(
                emotion_class="neutral",
                intensity="low",
                emotional_risk="low",
                support_mode="blended",
                support_preference=previous.support_preference if previous.support_preference != "unknown" else "unknown",
                stability="resolved",
                unresolved_topics=[],
                carryover_summary=str(lesson.summary or "Recent emotional carryover appears resolved."),
                last_observed_at=utc_now_iso(),
                carryover_until=grace_until,
                updated_at=utc_now_iso(),
            )
        else:
            now = datetime.now(timezone.utc)
            carryover_until = (now + timedelta(days=7)).isoformat()

            # Merge unresolved_topics with previous topics instead of
            # replacing, so that multiple emotional threads within the
            # same session are all preserved.
            new_topics = list(details.get("unresolved_topics", []))
            merged_topics = list(new_topics)
            for topic in previous.unresolved_topics:
                if topic and topic not in merged_topics:
                    merged_topics.append(topic)
            merged_topics = merged_topics[:5]

            # Keep the more severe emotion class when merging
            severity = {
                "neutral": 0, "relief": 0, "joy": 0,
                "frustration": 1, "anger": 2,
                "sadness": 3, "loneliness": 3,
                "anxiety": 4, "overwhelm": 5,
            }
            new_class = str(details.get("emotion_class", "neutral"))
            prev_class = previous.emotion_class or "neutral"
            if severity.get(prev_class, 0) > severity.get(new_class, 0):
                emotion_class = prev_class
            else:
                emotion_class = new_class

            current.user_emotional_state = UserEmotionalState(
                emotion_class=emotion_class,
                intensity=str(details.get("intensity", previous.intensity or "low")),
                emotional_risk=str(details.get("emotional_risk", previous.emotional_risk or "low")),
                support_mode=str(details.get("support_mode", previous.support_mode or "blended")),
                support_preference=str(details.get("support_preference", previous.support_preference or "unknown")),
                stability=str(details.get("stability", "fragile")),
                unresolved_topics=merged_topics,
                carryover_summary=str(lesson.summary or details.get("summary") or previous.carryover_summary),
                last_observed_at=now.isoformat(),
                carryover_until=carryover_until,
                updated_at=now.isoformat(),
            )
        await self.core_memory_scheduler.write(
            lesson.user_id,
            "user_emotional_state",
            current.user_emotional_state,
            event_id=lesson.id,
        )

    async def _apply_agent_continuity_state(self, lesson: Lesson) -> None:
        current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
        previous = current.agent_continuity_state
        details = dict(lesson.details)
        now = utc_now_iso()
        if lesson.category == "agent_state_shift":
            current.agent_continuity_state = AgentContinuityState(
                caution_level="high",
                warmth_level="medium" if previous.warmth_level == "low" else previous.warmth_level,
                repair_mode=True,
                recovery_mode=False,
                relational_confidence=max(0.2, previous.relational_confidence - 0.15),
                continuity_summary=str(lesson.summary or details.get("summary_hint") or previous.continuity_summary),
                active_signals=self._merge_signals(previous.active_signals, str(details.get("active_signal", "task_failure"))),
                last_event_at=now,
                last_shift_reason=str(details.get("summary_hint", lesson.summary)),
                updated_at=now,
            )
        else:
            current.agent_continuity_state = AgentContinuityState(
                caution_level="medium" if previous.caution_level == "high" else "low",
                warmth_level=previous.warmth_level if previous.warmth_level != "low" else "medium",
                repair_mode=False,
                recovery_mode=True,
                relational_confidence=min(0.9, previous.relational_confidence + 0.1),
                continuity_summary=str(lesson.summary or details.get("summary_hint") or "Agent continuity is recovering."),
                active_signals=self._merge_signals(previous.active_signals, str(details.get("active_signal", "task_success"))),
                last_event_at=now,
                last_shift_reason=str(details.get("summary_hint", lesson.summary)),
                updated_at=now,
            )
        await self.core_memory_scheduler.write(
            lesson.user_id,
            "agent_continuity_state",
            current.agent_continuity_state,
            event_id=lesson.id,
        )

    @staticmethod
    def _merge_signals(existing: list[str], signal: str) -> list[str]:
        merged = [item for item in existing if item and item != signal]
        if signal:
            merged.insert(0, signal)
        return merged[:4]

    async def _apply_world_model_candidate(
        self,
        user_id: str,
        proposed_change: dict[str, Any],
        *,
        event_id: str | None = None,
    ) -> None:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        world_model = current.world_model
        if proposed_change.get("kind") == "relationship_stage":
            from app.memory.core_memory import RelationshipStageState

            data = dict(proposed_change.get("relationship_stage", {}))
            world_model.relationship_stage = RelationshipStageState(
                stage=str(data.get("stage", "unfamiliar")),
                confidence=float(data.get("confidence", 0.0)),
                updated_at=str(data.get("updated_at", "")) or utc_now_iso(),
                entered_at=str(data.get("entered_at", "")) or utc_now_iso(),
                supports_vulnerability=bool(data.get("supports_vulnerability", False)),
                repair_needed=bool(data.get("repair_needed", False)),
                recent_transition_reason=str(data.get("recent_transition_reason", "")),
                recent_shared_events=list(data.get("recent_shared_events", [])),
            )
            await self.core_memory_scheduler.write(
                user_id, "world_model", world_model, event_id=event_id
            )
            return
        candidate = self._memory_from_dict(dict(proposed_change.get("memory", {})))
        if candidate is None:
            return
        if isinstance(candidate, RelationshipMemory):
            world_model.relationship_history = self._merge_memory(
                world_model.relationship_history, candidate
            )
            await self._promote_relationship(user_id, candidate)
        elif isinstance(candidate, FactualMemory):
            world_model.confirmed_facts = self._merge_memory(
                world_model.confirmed_facts, candidate
            )
        else:
            conflict = self._detect_conflict(world_model.confirmed_facts, candidate)
            if conflict is not None:
                candidate.status = "conflicted"
                candidate.conflict_with = [conflict.memory_key or conflict.content]
                world_model.memory_conflicts = self._merge_memory(
                    world_model.memory_conflicts, candidate
                )
            else:
                world_model.inferred_memories = self._merge_memory(
                    world_model.inferred_memories, candidate
                )
        await self.core_memory_scheduler.write(
            user_id, "world_model", world_model, event_id=event_id
        )
        if candidate.status != "conflicted":
            await self._mark_mid_term_item_promoted(user_id, candidate)
        if self.relationship_state_machine is not None:
            await self.relationship_state_machine.evaluate(
                user_id=user_id, event_id=event_id
            )

    def _classify_memory(self, lesson: Lesson) -> DurableMemory:
        source = str(lesson.details.get("source", "lesson"))
        content = (
            lesson.lesson_text
            or lesson.summary
            or lesson.root_cause
            or "Captured lesson"
        )
        confidence = float(lesson.confidence or 0.0)
        sensitivity = "sensitive" if lesson.details.get("sensitive") else "normal"
        updated_at = utc_now_iso()
        support_preference = str(lesson.details.get("support_preference", "")).strip()
        proactivity_preference = str(
            lesson.details.get("proactivity_preference", "")
        ).strip()
        preference_relation = str(lesson.details.get("preference_relation", "")).strip()
        preference_object = str(lesson.details.get("preference_object", "")).strip()

        if (
            lesson.domain == "explicit_preference"
            and preference_relation in {"likes", "dislikes", "prefers", "uses"}
            and preference_object
        ):
            memory_key = self._explicit_preference_memory_key(
                preference_relation, preference_object
            )
            preference_content = content or self._explicit_preference_summary(
                preference_relation, preference_object
            )
            if lesson.details.get("explicit_user_statement", False):
                return FactualMemory(
                    content=preference_content,
                    source=source,
                    confidence=max(confidence, 0.85),
                    updated_at=updated_at,
                    confirmed_by_user=bool(
                        lesson.details.get("explicit_user_confirmation", True)
                    ),
                    time_horizon="long_term",
                    status="active",
                    sensitivity=sensitivity,
                    memory_key=memory_key,
                    metadata={
                        "lesson_id": lesson.id,
                        "category": lesson.category,
                        "preference_relation": preference_relation,
                        "preference_object": preference_object,
                    },
                )
            return InferredMemory(
                content=preference_content,
                source=source,
                confidence=max(confidence, 0.8),
                updated_at=updated_at,
                confirmed_by_user=False,
                time_horizon="medium_term",
                status="active",
                sensitivity=sensitivity,
                memory_key=memory_key.replace("fact:", "inference:", 1),
                metadata={
                    "lesson_id": lesson.id,
                    "category": lesson.category,
                    "preference_relation": preference_relation,
                    "preference_object": preference_object,
                },
            )

        if (
            lesson.domain == "implicit_preference"
            and preference_relation in {"likes", "dislikes", "prefers", "uses"}
            and preference_object
        ):
            durability = str(lesson.details.get("preference_durability", "unknown")).strip()
            strength = str(lesson.details.get("preference_strength", "implicit")).strip()
            memory_tier = str(lesson.details.get("memory_tier", "inference_candidate")).strip()
            implicit_content = content or self._implicit_preference_summary(
                preference_relation, preference_object
            )
            return InferredMemory(
                content=implicit_content,
                source=source,
                confidence=min(max(confidence, 0.55), 0.74),
                updated_at=updated_at,
                confirmed_by_user=False,
                time_horizon="short_term" if durability == "situational" else "medium_term",
                status="active",
                sensitivity=sensitivity,
                memory_key=self._implicit_preference_memory_key(
                    preference_relation, preference_object
                ),
                metadata={
                    "lesson_id": lesson.id,
                    "category": lesson.category,
                    "preference_relation": preference_relation,
                    "preference_object": preference_object,
                    "preference_durability": durability,
                    "preference_strength": strength,
                    "memory_tier": memory_tier,
                    "speaker_attribution": str(
                        lesson.details.get("speaker_attribution", "uncertain")
                    ),
                    "evidence_type": str(
                        lesson.details.get("evidence_type", "implicit_expression")
                    ),
                },
            )

        if lesson.domain == "support_preference" and support_preference in {
            "listening",
            "problem_solving",
            "mixed",
        }:
            memory_key = f"support_preference:{support_preference}"
            if lesson.details.get("explicit_user_statement", False):
                return FactualMemory(
                    content=content
                    or f"User prefers {support_preference.replace('_', '-')} support.",
                    source=source,
                    confidence=max(confidence, 0.85),
                    updated_at=updated_at,
                    confirmed_by_user=bool(
                        lesson.details.get("explicit_user_confirmation", True)
                    ),
                    time_horizon="long_term",
                    status="active",
                    sensitivity=sensitivity,
                    memory_key=memory_key,
                    metadata={"lesson_id": lesson.id, "category": lesson.category},
                )
            return InferredMemory(
                content=content
                or f"User often prefers {support_preference.replace('_', '-')} support.",
                source=source,
                confidence=max(confidence, 0.8),
                updated_at=updated_at,
                confirmed_by_user=False,
                time_horizon="medium_term",
                status="active",
                sensitivity=sensitivity,
                memory_key=memory_key,
                metadata={"lesson_id": lesson.id, "category": lesson.category},
            )

        if lesson.domain == "proactivity_preference" and proactivity_preference in {
            "allow",
            "suppress",
        }:
            memory_key = f"proactivity_preference:{proactivity_preference}"
            if lesson.details.get("explicit_user_statement", False):
                return FactualMemory(
                    content=content
                    or (
                        "User explicitly allows gentle follow-up on important topics."
                        if proactivity_preference == "allow"
                        else "User explicitly does not want proactive follow-up or reminders."
                    ),
                    source=source,
                    confidence=max(confidence, 0.85),
                    updated_at=updated_at,
                    confirmed_by_user=bool(
                        lesson.details.get("explicit_user_confirmation", True)
                    ),
                    time_horizon="long_term",
                    status="active",
                    sensitivity=sensitivity,
                    memory_key=memory_key,
                    metadata={"lesson_id": lesson.id, "category": lesson.category},
                )
            return InferredMemory(
                content=content
                or (
                    "User may be open to gentle follow-up on important topics."
                    if proactivity_preference == "allow"
                    else "User may prefer no proactive follow-up."
                ),
                source=source,
                confidence=max(confidence, 0.8),
                updated_at=updated_at,
                confirmed_by_user=False,
                time_horizon="medium_term",
                status="active",
                sensitivity=sensitivity,
                memory_key=memory_key,
                metadata={"lesson_id": lesson.id, "category": lesson.category},
            )

        if lesson.subject and lesson.relation and lesson.object:
            return RelationshipMemory(
                content=content
                or f"{lesson.subject} {lesson.relation} {lesson.object}",
                source=source,
                confidence=confidence,
                updated_at=updated_at,
                confirmed_by_user=bool(
                    lesson.details.get("explicit_user_confirmation", False)
                ),
                time_horizon="long_term",
                status="active",
                sensitivity=sensitivity,
                memory_key=f"relationship:{lesson.subject}:{lesson.relation}:{lesson.object}",
                metadata={"lesson_id": lesson.id, "category": lesson.category},
                subject=lesson.subject,
                relation=lesson.relation,
                object=lesson.object,
            )

        if lesson.details.get("explicit_user_statement", False):
            return FactualMemory(
                content=content,
                source=source,
                confidence=max(confidence, 0.8),
                updated_at=updated_at,
                confirmed_by_user=bool(
                    lesson.details.get("explicit_user_confirmation", True)
                ),
                time_horizon="long_term",
                status="active",
                sensitivity=sensitivity,
                memory_key=f"fact:{lesson.domain}:{content.lower()}",
                metadata={"lesson_id": lesson.id, "category": lesson.category},
            )

        return InferredMemory(
            content=content,
            source=source,
            confidence=confidence or 0.6,
            updated_at=updated_at,
            confirmed_by_user=False,
            time_horizon="medium_term",
            status="active",
            sensitivity=sensitivity,
            memory_key=f"inference:{lesson.domain}:{content.lower()}",
            metadata={
                "lesson_id": lesson.id,
                "category": lesson.category,
                **(
                    {"mid_term_memory_key": str(lesson.details.get("mid_term_memory_key", ""))}
                    if lesson.details.get("mid_term_memory_key")
                    else {}
                ),
            },
        )

    def _requires_confirmation(self, candidate: DurableMemory) -> bool:
        if str(candidate.memory_key).startswith("support_preference:"):
            return False
        if candidate.metadata.get("memory_tier") == "session_hint":
            return False
        return (
            candidate.sensitivity == "sensitive"
            or candidate.confidence < 0.75
            or not candidate.confirmed_by_user
        )

    def _detect_conflict(
        self,
        existing_facts: list[FactualMemory],
        candidate: InferredMemory,
    ) -> FactualMemory | None:
        candidate_key = candidate.memory_key.replace("inference:", "fact:", 1)
        for item in existing_facts:
            if item.memory_key == candidate_key and item.content != candidate.content:
                return item
        return None

    async def _promote_relationship(
        self, user_id: str, candidate: RelationshipMemory
    ) -> None:
        if self.graph_store is None:
            return
        await self.graph_store.upsert_relation(
            user_id=user_id,
            subject=candidate.subject,
            relation=candidate.relation,
            object=candidate.object,
            confidence=candidate.confidence,
            source=candidate.source,
            confirmed_by_user=candidate.confirmed_by_user,
            status=candidate.status,
            time_horizon=candidate.time_horizon,
            sensitivity=candidate.sensitivity,
            conflict_with=candidate.conflict_with,
            metadata=dict(candidate.metadata),
        )

    async def _create_memory_confirmation_task(
        self, lesson: Lesson, candidate: DurableMemory
    ) -> None:
        if self.task_store is None or self.blackboard is None:
            return
        confirmation = MemoryConfirmationRequest(
            memory_key=candidate.memory_key,
            candidate_content=candidate.content,
            truth_type=candidate.truth_type,
            source=candidate.source,
            reason=(
                "This memory is sensitive or not yet confident enough to promote without explicit confirmation."
            ),
            metadata={"lesson_id": lesson.id, "confidence": candidate.confidence},
        )
        task = Task(
            intent="memory_confirmation",
            status="pending",
            metadata={
                "user_id": lesson.user_id,
                "memory_confirmation": {
                    "memory_key": candidate.memory_key,
                    "candidate": asdict(candidate),
                    "request": asdict(confirmation),
                },
            },
        )
        await self.task_store.create(task)
        request = HitlRequest(
            task_id=task.id,
            title="Memory confirmation required",
            description=confirmation.reason,
            options=list(confirmation.options),
            risk_level="medium" if candidate.sensitivity == "normal" else "high",
            metadata={"memory_confirmation": asdict(confirmation)},
        )
        await self.blackboard.on_task_waiting_hitl(task, request)

    async def _create_evolution_candidate_task(
        self,
        user_id: str,
        candidate: EvolutionCandidate,
    ) -> None:
        if self.task_store is None or self.blackboard is None:
            return
        if candidate.metadata.get("hitl_task_id"):
            return
        request_payload = EvolutionCandidateRequest(
            candidate_id=candidate.id,
            affected_area=candidate.affected_area,
            risk_level=candidate.risk_level,
            evidence_summary=candidate.evidence_summary,
            proposed_change=dict(candidate.proposed_change),
            reason="This evolution candidate is high-risk and requires explicit approval before long-term application.",
            metadata={"source_event_ids": list(candidate.source_event_ids)},
        )
        task = Task(
            intent="evolution_candidate_review",
            status="pending",
            metadata={
                "user_id": user_id,
                "evolution_candidate": asdict(request_payload),
            },
        )
        await self.task_store.create(task)
        self.candidate_manager.attach_hitl_task(candidate.id, task.id)
        request = HitlRequest(
            task_id=task.id,
            title="Evolution approval required",
            description=request_payload.reason,
            options=list(request_payload.options),
            risk_level=candidate.risk_level,
            metadata={"evolution_candidate": asdict(request_payload)},
        )
        await self.blackboard.on_task_waiting_hitl(task, request)

    @staticmethod
    def _world_model_dedupe_key(candidate: DurableMemory) -> str:
        if isinstance(candidate, RelationshipMemory):
            return f"relationship:{candidate.subject}:{candidate.relation}:{candidate.object}"
        return candidate.memory_key

    @staticmethod
    def _world_model_risk(
        candidate: DurableMemory,
        conflict: FactualMemory | None,
    ) -> str:
        if conflict is not None:
            return "high"
        if isinstance(candidate, InferredMemory):
            return "medium"
        if candidate.sensitivity == "sensitive":
            return "high"
        return "low"

    @staticmethod
    def _merge_memory(existing: list[Any], candidate: Any) -> list[Any]:
        merged: list[Any] = []
        replaced = False
        candidate_key = getattr(candidate, "memory_key", "") or ""
        for item in existing:
            item_key = getattr(item, "memory_key", "") or ""
            if candidate_key and item_key == candidate_key:
                # Existing confirmed item beats unconfirmed candidate → keep existing, drop candidate.
                if getattr(item, "confirmed_by_user", False) and not getattr(
                    candidate, "confirmed_by_user", False
                ):
                    merged.append(item)
                    replaced = True
                    continue
                # Both confirmed → supersede old, add new below.
                if getattr(candidate, "confirmed_by_user", False) and getattr(
                    item, "confirmed_by_user", False
                ):
                    item.status = "superseded"
                    merged.append(item)
                    merged.append(candidate)
                    replaced = True
                    continue
                # Otherwise (e.g. both unconfirmed, or candidate confirmed + item not) → replace old with new.
                merged.append(candidate)
                replaced = True
                continue
            merged.append(item)
        if not replaced:
            merged.append(candidate)
        return merged

    @staticmethod
    def _memory_from_dict(data: dict[str, Any]) -> DurableMemory | None:
        truth_type = data.get("truth_type", "fact")
        if truth_type == "relationship":
            return RelationshipMemory(**data)
        if truth_type == "inference":
            return InferredMemory(**data)
        if truth_type == "fact":
            return FactualMemory(**data)
        return None

    async def _mark_mid_term_item_promoted(self, user_id: str, candidate: DurableMemory) -> None:
        if self.mid_term_memory_store is None:
            return
        mid_term_memory_key = str(candidate.metadata.get("mid_term_memory_key", ""))
        if not mid_term_memory_key:
            return
        await self.mid_term_memory_store.mark_promoted(
            user_id=user_id,
            memory_key=mid_term_memory_key,
            promoted_memory_key=candidate.memory_key,
        )

    async def _suppress_mid_term_item(self, user_id: str, candidate: DurableMemory, *, reason: str) -> None:
        if self.mid_term_memory_store is None:
            return
        mid_term_memory_key = str(candidate.metadata.get("mid_term_memory_key", ""))
        if not mid_term_memory_key:
            return
        await self.mid_term_memory_store.suppress_related(
            user_id=user_id,
            memory_key=mid_term_memory_key,
            reason=reason,
        )

    @staticmethod
    def _relationship_observation(lesson: Lesson) -> dict[str, Any]:
        return {
            "summary": lesson.summary,
            "lesson_text": lesson.lesson_text,
            "content": lesson.root_cause,
            "context_id": str(
                lesson.details.get("session_id") or lesson.source_task_id or lesson.id
            ),
            "emotional_risk": lesson.details.get("emotional_risk"),
        }

    async def _apply_agent_emotional_state(self, lesson: Lesson) -> None:
        """Update the agent's own emotional state based on interaction signals."""
        current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
        previous = current.agent_emotional_state
        details = dict(lesson.details)
        now = utc_now_iso()

        mood = str(details.get("mood", previous.mood or "neutral"))
        mood_intensity = str(details.get("mood_intensity", previous.mood_intensity or "low"))
        toward_user = str(details.get("toward_user", previous.toward_user or "neutral"))
        toward_user_intensity = str(details.get("toward_user_intensity", previous.toward_user_intensity or "low"))

        # Merge curiosity topics (keep max 5)
        new_curiosity = list(details.get("curiosity_topics", []))
        merged_curiosity = list(new_curiosity)
        for topic in previous.curiosity_topics:
            if topic and topic not in merged_curiosity:
                merged_curiosity.append(topic)
        merged_curiosity = merged_curiosity[:5]

        # Merge topic affinities (update existing, append new, keep max 8)
        new_affinities_raw = list(details.get("topic_affinities", []))
        existing_map = {a.topic: a for a in previous.topic_affinities}
        for raw in new_affinities_raw:
            topic = str(raw.get("topic", ""))
            if not topic:
                continue
            if topic in existing_map:
                a = existing_map[topic]
                a.engagement_level = min(1.0, a.engagement_level + 0.1)
                a.last_discussed_at = now
                a.mention_count += 1
                a.sentiment = str(raw.get("sentiment", a.sentiment))
            else:
                existing_map[topic] = TopicAffinity(
                    topic=topic,
                    engagement_level=float(raw.get("engagement_level", 0.5)),
                    last_discussed_at=now,
                    mention_count=1,
                    sentiment=str(raw.get("sentiment", "positive")),
                )
        merged_affinities = sorted(
            existing_map.values(),
            key=lambda a: a.engagement_level,
            reverse=True,
        )[:8]

        # Compute valence from mood
        valence_map = {
            "content": 0.5, "curious": 0.3, "warm": 0.6, "playful": 0.4,
            "reflective": 0.1, "neutral": 0.0, "concerned": -0.2, "low": -0.4,
        }
        emotional_valence = valence_map.get(mood, 0.0)

        current.agent_emotional_state = AgentEmotionalState(
            mood=mood,
            mood_intensity=mood_intensity,
            toward_user=toward_user,
            toward_user_intensity=toward_user_intensity,
            emotional_valence=emotional_valence,
            curiosity_topics=merged_curiosity,
            topic_affinities=merged_affinities,
            miss_user_after_hours=previous.miss_user_after_hours,
            last_interaction_at=now,
            mood_reason=str(details.get("mood_reason", previous.mood_reason or "")),
            toward_user_reason=str(details.get("toward_user_reason", previous.toward_user_reason or "")),
            updated_at=now,
        )
        await self.core_memory_scheduler.write(
            lesson.user_id,
            "agent_emotional_state",
            current.agent_emotional_state,
            event_id=lesson.id,
        )

    async def _apply_shared_experience(self, lesson: Lesson) -> None:
        """Record a shared experience between agent and user."""
        current = deepcopy(await self.core_memory_cache.get(lesson.user_id))
        world_model = current.world_model
        details = dict(lesson.details)

        experience = SharedExperience(
            summary=str(lesson.summary or lesson.lesson_text or "Shared moment"),
            emotional_tone=str(details.get("emotional_tone", "neutral")),
            topic_key=str(details.get("topic_key", lesson.domain or "")),
            session_id=str(details.get("session_id", "")),
            importance=details.get("importance", "medium"),
            metadata={"lesson_id": lesson.id},
        )

        # Keep max 10 shared experiences, oldest dropped first
        world_model.shared_experiences.append(experience)
        if len(world_model.shared_experiences) > 10:
            world_model.shared_experiences = world_model.shared_experiences[-10:]

        await self.core_memory_scheduler.write(
            lesson.user_id,
            "world_model",
            world_model,
            event_id=lesson.id,
        )

    @staticmethod
    def _explicit_preference_memory_key(relation: str, object_value: str) -> str:
        normalized_object = (
            object_value.strip().lower().replace(" ", "_").replace("/", "_")
        )
        return f"fact:explicit_preference:{relation}:{normalized_object}"

    @staticmethod
    def _explicit_preference_summary(relation: str, object_value: str) -> str:
        verb = {
            "likes": "likes",
            "dislikes": "dislikes",
            "prefers": "prefers",
            "uses": "uses",
        }.get(relation, relation)
        return f"User {verb} {object_value}."

    @staticmethod
    def _implicit_preference_memory_key(relation: str, object_value: str) -> str:
        normalized_object = (
            object_value.strip().lower().replace(" ", "_").replace("/", "_")
        )
        return f"inference:implicit_preference:{relation}:{normalized_object}"

    @staticmethod
    def _implicit_preference_summary(relation: str, object_value: str) -> str:
        verb = {
            "likes": "may like",
            "dislikes": "may dislike",
            "prefers": "may prefer",
            "uses": "may often use",
        }.get(relation, f"may {relation}")
        return f"User {verb} {object_value}."
