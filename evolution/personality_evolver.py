from typing import Optional
from domain.memory import PersonalityState, BehavioralRule
from domain.evolution import InteractionSignal, EvolutionEntry


class LLMInterfaceDummy:
    """LLM 调用占位实现"""

    async def generate(self, prompt: str) -> str:
        print(f"[LLM] 生成调用（占位）: {prompt[:100]}...")
        return "基于更新后的 traits 生成的基调描述"


class EvolutionJournalDummy:
    """EvolutionJournal 占位实现"""

    async def record(self, entry: EvolutionEntry) -> None:
        print(f"[EvolutionJournal] 记录: {entry.type} - {entry.summary}")


class PersonalityEvolver:
    """
    人格进化器：双速进化机制（快适应 + 慢进化）。
    - 快适应：Session 级即时响应，不写入 Core Memory
    - 慢进化：跨 Session，规则晋升 + traits 微调 + 基调重生成
    """

    FAST_WINDOW_SIZE = 3
    FAST_MAX_ADAPTATIONS = 5

    SLOW_UPDATE_FREQUENCY = 10
    SIGNAL_CONFIRMATION = 3
    RULE_PROMOTE_THRESHOLD = 0.7
    RULE_DECAY_THRESHOLD = 0.3

    LEARNING_RATE = 0.05
    DRIFT_THRESHOLD = 0.3
    HARD_GUARDRAILS = {
        "autonomy": (0.2, 0.95),
        "warmth": (0.3, 1.0),
        "caution": (0.4, 0.9),
    }

    def __init__(
        self,
        core_memory_cache: "CoreMemoryCache",
        llm_lite: Optional[LLMInterfaceDummy] = None,
        evolution_journal: Optional[EvolutionJournalDummy] = None,
    ):
        from core.memory_cache import CoreMemoryCache

        self.core_memory_cache: CoreMemoryCache = core_memory_cache
        self.llm_lite = llm_lite or LLMInterfaceDummy()
        self.evolution_journal = evolution_journal or EvolutionJournalDummy()
        self._signal_buffer: dict[str, list[InteractionSignal]] = {}

    async def fast_adapt(
        self,
        signal: InteractionSignal,
        user_id: str,
    ) -> Optional[str]:
        """
        快适应：Session 内即时响应用户偏好信号。
        不写入 Core Memory，但记录到信号缓冲区供慢进化统计。
        """
        adaptation = await self._detect_fast_signal(signal)
        if not adaptation:
            return None

        core_mem = self.core_memory_cache.get(user_id)
        current = core_mem.personality

        if len(current.session_adaptations) >= self.FAST_MAX_ADAPTATIONS:
            current.session_adaptations.pop(0)

        current.session_adaptations.append(adaptation)

        self._buffer_signal(adaptation, signal)

        await self.evolution_journal.record(
            {
                "type": "fast_adaptation",
                "summary": f"本次对话适应：{adaptation}",
                "detail": {"rule": adaptation, "signal": signal.model_dump()},
                "session_id": signal.session_id,
            }
        )

        self.core_memory_cache.set(user_id, core_mem)
        return adaptation

    async def slow_evolve(
        self,
        signals: list[InteractionSignal],
        user_id: str,
    ) -> None:
        """
        慢进化：跨 Session 累积，执行三个操作：
        1. 晋升：高频快适应规则 → 持久行为规则
        2. 淘汰：低置信度规则清理
        3. traits 微调 + 基调重生成
        """
        core_mem = self.core_memory_cache.get(user_id)
        current = core_mem.personality
        changed = False

        candidates = await self._get_promotion_candidates(user_id)
        for candidate in candidates:
            if candidate["frequency"] >= self.SIGNAL_CONFIRMATION:
                new_rule = BehavioralRule(
                    content=candidate["rule"],
                    source="slow_evolution",
                    confidence=min(1.0, candidate["frequency"] / 10.0),
                )
                if not self._is_duplicate_rule(current.behavioral_rules, new_rule):
                    current.behavioral_rules.append(new_rule)
                    changed = True
                    await self.evolution_journal.record(
                        {
                            "type": "rule_promoted",
                            "summary": f"新行为规则确认：{new_rule.content}",
                            "detail": {
                                "rule": new_rule.model_dump(),
                                "frequency": candidate["frequency"],
                            },
                        }
                    )

        before_count = len(current.behavioral_rules)
        current.behavioral_rules = [
            r
            for r in current.behavioral_rules
            if r.is_pinned or r.confidence >= self.RULE_DECAY_THRESHOLD
        ]
        if len(current.behavioral_rules) < before_count:
            decayed_count = before_count - len(current.behavioral_rules)
            await self.evolution_journal.record(
                {
                    "type": "rule_decayed",
                    "summary": f"淘汰了 {decayed_count} 条低置信度规则",
                    "detail": {"count": decayed_count},
                }
            )
            changed = True

        if len(current.behavioral_rules) > current.MAX_RULES:
            pinned = [r for r in current.behavioral_rules if r.is_pinned]
            unpinned = sorted(
                [r for r in current.behavioral_rules if not r.is_pinned],
                key=lambda r: r.confidence,
                reverse=True,
            )
            current.behavioral_rules = (
                pinned + unpinned[: current.MAX_RULES - len(pinned)]
            )
            changed = True

        trait_updates = self._aggregate_trait_signals(signals)
        if trait_updates:
            current.snapshot_history.append(current.traits_internal.copy())
            current.snapshot_history = current.snapshot_history[-5:]

            for trait, signal_value in trait_updates.items():
                old = current.traits_internal.get(trait, 0.5)
                new_val = (
                    old * (1 - self.LEARNING_RATE) + signal_value * self.LEARNING_RATE
                )
                lo, hi = self.HARD_GUARDRAILS.get(trait, (0.0, 1.0))
                current.traits_internal[trait] = max(lo, min(hi, new_val))

            if self._detect_drift(current):
                await self._rollback(current)
                await self.evolution_journal.record(
                    {
                        "type": "baseline_shifted",
                        "summary": "人格漂移检测，回滚到上一版本",
                        "detail": {"drift_detected": True},
                    }
                )
                return

            current.baseline_description = await self._regenerate_baseline(
                current.traits_internal
            )
            changed = True
            await self.evolution_journal.record(
                {
                    "type": "baseline_shifted",
                    "summary": f"人格基调更新：{current.baseline_description}",
                    "detail": {
                        "baseline_description": current.baseline_description,
                        "traits": current.traits_internal,
                    },
                }
            )

        if changed:
            current.version += 1
            self.core_memory_cache.set(user_id, core_mem)

    async def _detect_fast_signal(self, signal: InteractionSignal) -> Optional[str]:
        if signal.type == "explicit_instruction":
            return signal.content

        if signal.type == "implicit_behavior":
            recent = self._get_recent_signals(signal.session_id, self.FAST_WINDOW_SIZE)
            if self._is_consistent_pattern(recent):
                return await self._generate_rule_from_pattern(recent)

        return None

    def _buffer_signal(self, adaptation: str, signal: InteractionSignal) -> None:
        key = f"{signal.behavior_tag or 'general'}"
        if key not in self._signal_buffer:
            self._signal_buffer[key] = []
        self._signal_buffer[key].append(signal)

    async def _get_promotion_candidates(self, user_id: str) -> list[dict]:
        candidates = []
        for tag, signals in self._signal_buffer.items():
            rule = await self._generate_rule_from_pattern(
                signals[-self.SIGNAL_CONFIRMATION :]
            )
            candidates.append(
                {
                    "rule": rule,
                    "tag": tag,
                    "frequency": len(signals),
                }
            )
        return candidates

    def _get_recent_signals(
        self, session_id: str, window: int
    ) -> list[InteractionSignal]:
        all_signals = []
        for signals in self._signal_buffer.values():
            all_signals.extend(signals)
        all_signals.sort(key=lambda s: s.turn_index, reverse=True)
        return all_signals[:window]

    def _is_consistent_pattern(self, signals: list[InteractionSignal]) -> bool:
        if len(signals) < 2:
            return False
        tags = [s.behavior_tag for s in signals if s.behavior_tag]
        return len(set(tags)) == 1

    async def _generate_rule_from_pattern(
        self, signals: list[InteractionSignal]
    ) -> str:
        descriptions = [s.content for s in signals]
        prompt = f"""用户近期的行为模式如下：
{descriptions}

请生成一条简洁的行为规则（不超过20字），描述 AI 应如何调整回复风格。
仅输出规则文本，不要解释。"""
        return await self.llm_lite.generate(prompt)

    def _is_duplicate_rule(
        self,
        existing_rules: list[BehavioralRule],
        new_rule: BehavioralRule,
    ) -> bool:
        for rule in existing_rules:
            if self._semantic_similarity(rule.content, new_rule.content) > 0.85:
                if new_rule.confidence > rule.confidence:
                    rule.content = new_rule.content
                    rule.confidence = new_rule.confidence
                return True
        return False

    def _semantic_similarity(self, text1: str, text2: str) -> float:
        set1 = set(text1)
        set2 = set(text2)
        if not set1 or not set2:
            return 0.0
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        return intersection / union if union > 0 else 0.0

    def _aggregate_trait_signals(
        self, signals: list[InteractionSignal]
    ) -> dict[str, float]:
        updates = {}
        for signal in signals:
            if signal.type == "implicit_behavior":
                if signal.behavior_tag == "shorten_response":
                    updates["directness"] = updates.get("directness", 0) + 0.1
                elif signal.behavior_tag == "language_switch":
                    pass
                elif signal.behavior_tag == "repeated_correction":
                    updates["caution"] = updates.get("caution", 0) + 0.05
        return updates

    def _detect_drift(self, personality: PersonalityState) -> bool:
        if len(personality.snapshot_history) < 2:
            return False

        latest = personality.snapshot_history[-1]
        previous = personality.snapshot_history[-2]

        drift_score = (
            sum(
                abs(latest.get(t, 0.5) - previous.get(t, 0.5))
                for t in ["directness", "warmth", "autonomy", "caution", "curiosity"]
            )
            / 5.0
        )

        return drift_score > self.DRIFT_THRESHOLD

    async def _rollback(self, personality: PersonalityState) -> None:
        if personality.snapshot_history:
            last_snapshot = personality.snapshot_history.pop()
            personality.traits_internal = last_snapshot

    async def _regenerate_baseline(self, traits: dict[str, float]) -> str:
        prompt = f"""根据以下人格特质数值，生成一句简洁的人格基调描述（不超过30字）：
{traits}
示例：直接、技术导向、尊重用户自主性的合作者"""
        return await self.llm_lite.generate(prompt)
