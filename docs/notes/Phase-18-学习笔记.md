# Phase 18 学习笔记：受控进化管道

> **前置阶段**：[[Phase-17-学习笔记]]  
> **目标**：建立受控进化候选管道，引入风险分级和审批机制，取代直接长期写入  
> **里程碑**：本阶段完成后进化系统具备候选生命周期管理、双路径HITL、风险分级策略

---

## 目录

- [概述](#概述)
- [1. Phase 18 文件清单](#1-phase-18-文件清单)
- [2. 为什么需要受控进化管道](#2-为什么需要受控进化管道)
- [3. 候选生命周期类型](#3-候选生命周期类型)
- [4. EvolutionCandidateManager 设计](#4-evolutioncandidatemanager-设计)
- [5. 风险分级策略](#5-风险分级策略)
- [6. CognitionUpdater 重写](#6-cognitionupdater-重写)
- [7. PersonalityEvolver 重写](#7-personalityevolver-重写)
- [8. 双路径 HITL 机制](#8-双路径-hitl-机制)
- [9. Journal 事件标准化](#9-journal-事件标准化)
- [10. Runtime 健康暴露](#10-runtime-健康暴露)
- [11. 验证与验收](#11-验证与验收)
- [12. Explicitly Not Done Yet](#12-explicitly-not-done-yet)
- [13. Phase 18 的意义](#13-phase-18-的意义)

---

## 概述

### 目标

Phase 18 的目标是**建立受控进化管道**，让系统具备：

- 显式候选生命周期（created → pending → applied/reverted）
- 风险分级策略（low/medium/high 自动Apply阈值不同）
- 高风险进化的用户审批机制
- 双路径 HITL（memory_confirmation vs evolution_candidate）
- 候选去重和聚合能力

### Phase 17 到 Phase 18 的演进

Phase 17 建立了人格稳定性和会话适应机制，Phase 18 则关注进化的**受控性**：

```
Phase 17 完成时
     ↓
人格系统具备版本化 + 回滚能力
     ↓
slow_evolve() 可直接修改长期人格
     ↓
但仍存在问题：
     ↓
     ↓
┌─────────────────────────────────────────┐
│  Phase 17 的进化问题                      │
├─────────────────────────────────────────┤
│  • slow_evolve() 直接写入，无审批          │
│  • 高风险变化（如删除核心规则）无确认       │
│  • 进化无去重，重复信号可能产生多版本       │
│  • self-cognition 更新直接修改，无候选      │
│  • world-model 更新直接写入，无生命周期     │
└─────────────────────────────────────────┘

Phase 18 新增
     ↓
候选管道（candidate pipeline）
     ↓
所有长期变化经过候选 → 审批 → 应用
     ↓
风险分级：高风险需用户HITL审批
     ↓
去重 + 聚合，避免重复候选
```

### 新的系统形态

```
进化信号 → 候选管道
     ↓
┌─────────────────────────────────────────┐
│  EvolutionCandidateManager               │
├─────────────────────────────────────────┤
│  1. 候选聚合（user_id / affected_area）    │
│  2. 去重（dedupe_key）                   │
│  3. 风险分级（low/medium/high）           │
│  4. 审批策略（auto-apply / HITL）         │
└─────────────────────────────────────────┘
     ↓
┌─────────────────────────────────────────┐
│  候选生命周期                             │
├─────────────────────────────────────────┤
│  created → pending → applied            │
│                 ↘→ reverted             │
└─────────────────────────────────────────┘
     ↓
低风险 → auto-apply
中风险 → auto-apply（需多证据）
高风险 → HITL 用户审批
```

---

## 1. Phase 18 文件清单

| 文件 | 内容 |
|------|------|
| `app/evolution/candidate_pipeline.py` | 候选管道模型和管理器（新增） |
| `app/evolution/cognition_updater.py` | 重写，改为提交候选而非直接写入 |
| `app/evolution/personality_evolver.py` | 重写，慢进化改为候选机制 |
| `app/tasks/models.py` | 新增 EvolutionCandidateRequest |
| `app/runtime/bootstrap.py` | 更新运行时连接 |
| `app/evolution/__init__.py` | 导出新类型 |
| `app/tasks/__init__.py` | 导出新HITL类型 |
| `tests/test_evolution_pipeline.py` | Phase 18 新增测试 |
| `tests/test_personality_evolver.py` | 更新覆盖候选机制 |
| `tests/test_relationship_memory.py` | 更新 |
| `tests/test_runtime_bootstrap.py` | 更新 |
| `tests/test_failure_semantics.py` | 更新 |
| `tests/test_observability.py` | 更新 |

---

## 2. 为什么需要受控进化管道

### 2.1 之前的问题

Phase 17 之前，进化系统存在以下问题：

| 问题 | 描述 | 影响 |
|------|------|------|
| **直接写入** | slow_evolve() 直接修改长期人格 | 高风险变化无审批 |
| **无风险分级** | 所有变化一视同仁 | 低风险变化也需等待 |
| **无去重** | 重复信号产生多个候选/版本 | 存储冗余，版本混乱 |
| **无生命周期** | world-model/cognition 更新无状态 | 无法追踪变化历史 |
| **HITL 混杂** | memory_confirmation 和 evolution 混用同一路径 | 语义不清 |

### 2.2 受控管道的价值

```
受控进化 = 候选 + 审批 + 风险分级

价值1: 安全
    ↓
高风险变化需用户审批
    ↓
不会意外删除核心人格

价值2: 可追溯
    ↓
候选生命周期完整记录
    ↓
每个变化都有审计日志

价值3: 去重
    ↓
dedupe_key 避免重复候选
    ↓
存储高效，版本清晰

价值4: 双路径分离
    ↓
memory_confirmation: 记忆真实性确认
evolution_candidate: 进化应用审批
    ↓
语义清晰，处理逻辑分离
```

---

## 3. 候选生命周期类型

### 3.1 EvolutionCandidate

```python
@dataclass
class EvolutionCandidate:
    """进化候选"""
    id: str                              # 候选ID
    user_id: str                         # 用户ID
    affected_area: EvolutionAffectedArea  # 受影响区域
    proposed_change: dict                # 提议的变更内容
    evidence: list[dict]                 # 支持证据
    evidence_count: int                  # 证据数量
    dedupe_key: str                      # 去重键
    risk_level: EvolutionRiskLevel        # 风险级别
    status: EvolutionCandidateStatus      # 当前状态
    created_at: datetime                 # 创建时间
    updated_at: datetime                 # 更新时间
    applied_at: datetime | None = None  # 应用时间
    rollback_reason: str | None = None   # 回滚原因
    context_ids: list[str] = field(default_factory=list)  # 关联上下文ID
    hitl_task_id: str | None = None      # HITL任务ID
```

### 3.2 EvolutionCandidateStatus

```python
class EvolutionCandidateStatus:
    CREATED = "created"           # 已创建，待处理
    PENDING = "pending"           # 等待审批/应用
    APPLIED = "applied"           # 已应用
    REVERTED = "reverted"         # 已回滚/拒绝
```

### 3.3 EvolutionRiskLevel

```python
class EvolutionRiskLevel:
    LOW = "low"      # 低风险：轻微行为规则调整
    MEDIUM = "medium"  # 中风险：特质/关系风格变化
    HIGH = "high"    # 高风险：核心人格变化、删除操作
```

### 3.4 EvolutionAffectedArea

```python
class EvolutionAffectedArea:
    SELF_COGNITION = "self_cognition"        # 自我认知区
    WORLD_MODEL_FACT = "world_model_fact"    # 世界模型-事实
    WORLD_MODEL_INFERENCE = "world_model_inference"  # 世界模型-推断
    WORLD_MODEL_RELATION = "world_model_relation"    # 世界模型-关系
    PERSONALITY_RULES = "personality_rules"    # 人格-规则
    PERSONALITY_TRAITS = "personality_traits"  # 人格-特质
    PERSONALITY_STYLE = "personality_style"   # 人格-风格
    BEHAVIORAL_RULES = "behavioral_rules"     # 行为规则
```

### 3.5 候选提交结果

```python
@dataclass
class EvolutionSubmissionResult:
    """候选提交结果"""
    submitted: bool              # 是否提交成功
    candidate_id: str | None    # 候选ID（提交成功时）
    deduped: bool               # 是否因去重被忽略
    auto_applied: bool          # 是否自动应用
    action: Literal["created", "deduped", "applied", "hitl", "pending"]
    reason: str                 # 原因说明
```

---

## 4. EvolutionCandidateManager 设计

### 4.1 管理器职责

```python
class EvolutionCandidateManager:
    """候选管道管理器 - 内存实现"""
    
    def __init__(self) -> None:
        self._candidates: dict[str, EvolutionCandidate] = {}  # {candidate_id: candidate}
        self._indexes: dict[str, list[str]] = {}  # 多级索引
    
    async def submit(
        self,
        user_id: str,
        affected_area: EvolutionAffectedArea,
        proposed_change: dict,
        evidence: list[dict],
        context_ids: list[str],
    ) -> EvolutionSubmissionResult:
        """提交新候选"""
        ...
    
    async def apply_batch(self, user_id: str) -> list[EvolutionCandidate]:
        """批量应用就绪候选"""
        ...
    
    async def get_pending(self, user_id: str) -> list[EvolutionCandidate]:
        """获取待处理候选"""
        ...
    
    async def mark_applied(self, candidate_id: str) -> None:
        """标记候选已应用"""
        ...
    
    async def mark_reverted(
        self,
        candidate_id: str,
        reason: str,
    ) -> None:
        """标记候选已回滚"""
        ...
```

### 4.2 候选聚合

候选按 user_id 和 affected_area 聚合：

```python
async def submit(self, ...) -> EvolutionSubmissionResult:
    # 1. 生成分布式去重 key
    dedupe_key = self._make_dedupe_key(user_id, affected_area, proposed_change)
    
    # 2. 检查是否已存在相同候选
    existing = self._find_by_dedupe_key(user_id, dedupe_key)
    if existing:
        # 更新现有候选，追加证据
        existing.evidence.extend(evidence)
        existing.evidence_count = len(existing.evidence)
        existing.updated_at = utc_now()
        return EvolutionSubmissionResult(
            submitted=False,
            deduped=True,
            action="deduped",
            reason="duplicate_candidate_updated",
        )
    
    # 3. 评估风险级别
    risk_level = self._assess_risk(affected_area, proposed_change, evidence)
    
    # 4. 创建新候选
    candidate = EvolutionCandidate(
        id=str(uuid4()),
        user_id=user_id,
        affected_area=affected_area,
        proposed_change=proposed_change,
        evidence=evidence,
        evidence_count=len(evidence),
        dedupe_key=dedupe_key,
        risk_level=risk_level,
        status=EvolutionCandidateStatus.CREATED,
        created_at=utc_now(),
        updated_at=utc_now(),
        context_ids=context_ids,
    )
    
    # 5. 存储并索引
    self._candidates[candidate.id] = candidate
    self._index_by_dedupe_key(candidate)
    self._index_by_area(user_id, candidate)
    
    # 6. 评估是否自动应用
    return await self._evaluate_apply(candidate)
```

### 4.3 批量应用

```python
async def apply_batch(self, user_id: str) -> list[EvolutionCandidate]:
    """批量应用就绪候选"""
    applied = []
    
    for candidate in self._get_pending(user_id):
        # 评估应用条件
        can_apply = await self._can_auto_apply(candidate)
        
        if can_apply:
            candidate.status = EvolutionCandidateStatus.PENDING
            applied.append(candidate)
    
    return applied


async def _can_auto_apply(self, candidate: EvolutionCandidate) -> bool:
    """判断候选是否可以自动应用"""
    risk = candidate.risk_level
    evidence_count = candidate.evidence_count
    context_count = len(set(candidate.context_ids))
    
    if risk == EvolutionRiskLevel.LOW:
        # 低风险：>=2 证据即自动应用
        return evidence_count >= 2
    
    if risk == EvolutionRiskLevel.MEDIUM:
        # 中风险：>=3 证据 + >=2 唯一上下文
        return evidence_count >= 3 and context_count >= 2
    
    if risk == EvolutionRiskLevel.HIGH:
        # 高风险：永不自动应用，需 HITL
        return False
    
    return False
```

---

## 5. 风险分级策略

### 5.1 默认风险策略

Phase 18 使用固定默认策略：

| 风险级别 | auto-apply 条件 | 处理方式 |
|---------|----------------|---------|
| LOW | evidence_count >= 2 | 自动应用 |
| MEDIUM | evidence_count >= 3 **且** context_ids >= 2 | 自动应用 |
| HIGH | 任何条件 | HITL 用户审批 |

### 5.2 风险评估逻辑

```python
def _assess_risk(
    self,
    affected_area: EvolutionAffectedArea,
    proposed_change: dict,
    evidence: list[dict],
) -> EvolutionRiskLevel:
    """评估候选风险级别"""
    
    # 高风险区域
    HIGH_RISK_AREAS = {
        EvolutionAffectedArea.SELF_COGNITION,  # 自我认知
        EvolutionAffectedArea.PERSONALITY_RULES,  # 核心人格规则
    }
    
    # 中风险区域
    MEDIUM_RISK_AREAS = {
        EvolutionAffectedArea.PERSONALITY_TRAITS,  # 特质
        EvolutionAffectedArea.PERSONALITY_STYLE,  # 关系风格
        EvolutionAffectedArea.BEHAVIORAL_RULES,  # 行为规则
    }
    
    # 检查变更类型
    change_type = proposed_change.get("type", "")
    DELETE_OPERATIONS = {"delete", "remove", "clear"}
    
    if affected_area in HIGH_RISK_AREAS:
        return EvolutionRiskLevel.HIGH
    
    if change_type in DELETE_OPERATIONS:
        return EvolutionRiskLevel.HIGH
    
    if affected_area in MEDIUM_RISK_AREAS:
        return EvolutionRiskLevel.MEDIUM
    
    return EvolutionRiskLevel.LOW
```

### 5.3 HITL 触发条件

```python
async def _evaluate_apply(self, candidate: EvolutionCandidate) -> EvolutionSubmissionResult:
    """评估是否需要 HITL"""
    
    can_auto = await self._can_auto_apply(candidate)
    
    if can_auto:
        # 自动应用
        candidate.status = EvolutionCandidateStatus.PENDING
        return EvolutionSubmissionResult(
            submitted=True,
            candidate_id=candidate.id,
            auto_applied=True,
            action="applied",
            reason="auto_apply_low_risk",
        )
    
    if candidate.risk_level == EvolutionRiskLevel.HIGH:
        # 高风险 → HITL
        candidate.status = EvolutionCandidateStatus.PENDING
        return EvolutionSubmissionResult(
            submitted=True,
            candidate_id=candidate.id,
            auto_applied=False,
            action="hitl",
            reason="high_risk_requires_approval",
        )
    
    # 中风险但证据不足 → pending
    return EvolutionSubmissionResult(
        submitted=True,
        candidate_id=candidate.id,
        auto_applied=False,
        action="pending",
        reason="insufficient_evidence",
    )
```

---

## 6. CognitionUpdater 重写

### 6.1 之前：直接写入

Phase 17 的 CognitionUpdater 直接写入：

```python
# 旧逻辑
async def handle_lesson_generated(self, event: Event) -> None:
    lesson = event.payload["lesson"]
    
    if lesson.is_self_cognition:
        await self._write_self_cognition(lesson)  # 直接写入
    elif lesson.is_world_model:
        await self._write_world_model(lesson)  # 直接写入
```

### 6.2 现在：提交候选

Phase 18 的 CognitionUpdater 改为提交候选：

```python
async def handle_lesson_generated(self, event: Event) -> None:
    lesson = event.payload["lesson"]
    
    if lesson.is_self_cognition:
        # 自我认知 → 提交候选
        result = await self.candidate_manager.submit(
            user_id=lesson.user_id,
            affected_area=EvolutionAffectedArea.SELF_COGNITION,
            proposed_change={"type": "update", "content": lesson.content},
            evidence=[asdict(lesson)],
            context_ids=[lesson.session_id],
        )
        
        # Phase 16 的 memory_confirmation 仍然独立
    elif lesson.is_world_model:
        # 世界模型 → 提交候选
        area = self._classify_world_model_area(lesson)
        result = await self.candidate_manager.submit(
            user_id=lesson.user_id,
            affected_area=area,
            proposed_change={"type": "update", "content": lesson.content},
            evidence=[asdict(lesson)],
            context_ids=[lesson.session_id],
        )
        
        # world-model 写入现在分两阶段：
        # 1. 候选提交
        # 2. 实际应用（仅在候选 policy 返回 apply 后）
```

### 6.3 两阶段写入模式

Phase 18 的 world-model 写入变为两阶段：

```
阶段1: 候选提交
     ↓
lesson 分类 → 候选提交 → 候选评估
     ↓
阶段2: 实际应用
     ↓
候选 policy 返回 apply → 实际写入 → journal 记录
```

---

## 7. PersonalityEvolver 重写

### 7.1 之前：slow_evolve 直接修改

Phase 17 的 slow_evolve 直接修改长期人格：

```python
# 旧逻辑
async def slow_evolve(self, signals: list[InteractionSignal]) -> None:
    patterns = self._detect_repeated_patterns(signals)
    
    for pattern in patterns:
        if pattern.repeat_count >= REPEAT_THRESHOLD:
            # 直接修改长期人格
            await self._apply_long_term_change(pattern)  # ⚠️ 无审批
```

### 7.2 现在：候选机制

Phase 18 的 slow_evolve 改为候选机制：

```python
async def slow_evolve(self, signals: list[InteractionSignal]) -> None:
    patterns = self._detect_repeated_patterns(signals)
    
    for pattern in patterns:
        if pattern.repeat_count < REPEAT_THRESHOLD:
            continue
        
        # 1. 创建快照
        await self.snapshot_store.save(
            self.core_memory_cache.get(personality),
            reason="evolution"
        )
        
        # 2. 提交候选，而非直接应用
        area = self._pattern_to_area(pattern)
        result = await self.candidate_manager.submit(
            user_id=pattern.user_id,
            affected_area=area,
            proposed_change=self._pattern_to_change(pattern),
            evidence=[asdict(s) for s in self._get_signals_for_pattern(pattern)],
            context_ids=[s.session_id for s in self._get_signals_for_pattern(pattern)],
        )
        
        # 3. drift 检测仍作用于快照
        if self._detect_drift():
            # 4. 回滚时标记相关候选为 reverted
            await self._revert_related_candidates(pattern)


async def _revert_related_candidates(self, pattern: Any) -> None:
    """回滚时标记相关候选为 reverted"""
    candidates = await self.candidate_manager.get_pending(pattern.user_id)
    
    for candidate in candidates:
        if self._candidate_related_to_pattern(candidate, pattern):
            await self.candidate_manager.mark_reverted(
                candidate.id,
                reason="drift_rollback",
            )
```

### 7.3 高风险人格候选

```python
async def _submit_personality_candidate(
    self,
    user_id: str,
    area: EvolutionAffectedArea,
    change: dict,
    signals: list[InteractionSignal],
) -> EvolutionSubmissionResult:
    """提交人格候选"""
    
    result = await self.candidate_manager.submit(
        user_id=user_id,
        affected_area=area,
        proposed_change=change,
        evidence=[asdict(s) for s in signals],
        context_ids=[s.session_id for s in signals],
    )
    
    # 高风险人格候选 → HITL
    if result.action == "hitl":
        # 创建 HITL 任务
        await self._create_evolution_hitl_task(result.candidate_id)
    
    return result
```

---

## 8. 双路径 HITL 机制

### 8.1 两种 HITL 路径

Phase 18 明确区分两种 HITL 路径：

| 路径 | 用途 | metadata key |
|------|------|--------------|
| `memory_confirmation` | 记忆真实性确认（Phase 16） | 低置信度/敏感记忆 |
| `evolution_candidate` | 高风险进化应用审批（Phase 18） | 高风险人格/认知变化 |

### 8.2 EvolutionCandidateRequest

```python
@dataclass
class EvolutionCandidateRequest:
    """进化候选 HITL 请求"""
    candidate_id: str
    user_id: str
    affected_area: str
    proposed_change: dict
    evidence_summary: str
    risk_level: str
    evidence_count: int
    current_state_summary: str
    impact_description: str
    options: list[str] = field(default_factory=lambda: ["approve", "reject"])
```

### 8.3 HITL 处理分离

```python
# HITL 处理器现在根据 metadata key 区分
async def handle_hitl_feedback(task_id: str, decision: str, metadata: dict) -> None:
    
    if "memory_confirmation" in metadata:
        # Phase 16: 记忆确认路径
        await _handle_memory_confirmation(task_id, decision, metadata)
    
    elif "evolution_candidate" in metadata:
        # Phase 18: 进化候选审批路径
        await _handle_evolution_candidate(task_id, decision, metadata)
    
    else:
        raise ValueError(f"Unknown HITL metadata type: {metadata}")


async def _handle_evolution_candidate(
    task_id: str,
    decision: str,
    metadata: dict,
) -> None:
    """处理进化候选 HITL 反馈"""
    candidate_id = metadata["evolution_candidate"]["candidate_id"]
    
    if decision == "approve":
        # 应用候选
        await candidate_manager.mark_applied(candidate_id)
        # 执行实际的人格/认知变更
        await _apply_candidate_change(candidate_id)
    
    elif decision == "reject":
        # 拒绝候选
        await candidate_manager.mark_reverted(
            candidate_id,
            reason="user_rejected",
        )
```

---

## 9. Journal 事件标准化

### 9.1 候选生命周期事件

Phase 18 标准化了候选生命周期 Journal 事件：

| 事件 | 说明 |
|------|------|
| `evolution_candidate_created` | 候选已创建 |
| `evolution_candidate_updated` | 候选已更新（追加证据） |
| `evolution_candidate_pending` | 候选等待审批 |
| `evolution_candidate_applied` | 候选已应用 |
| `evolution_candidate_reverted` | 候选已回滚/拒绝 |

### 9.2 Journal Details 字段

```python
JOURNAL_CANDIDATE_DETAILS = {
    "candidate_id": str,          # 候选ID
    "candidate_status": str,      # 候选状态
    "risk_level": str,           # 风险级别
    "affected_area": str,        # 受影响区域
    "evidence_count": int,       # 证据数量
    "dedupe_key": str,           # 去重键
    "proposed_change": dict,      # 提议变更
    "rollback_reason": str | None,  # 回滚原因（reverted 时）
}
```

---

## 10. Runtime 健康暴露

### 10.1 健康端点更新

Phase 18 的 `/health` 端点现在暴露候选管道状态：

```python
def health_snapshot(self) -> dict[str, Any]:
    # ...
    candidate_stats = self._get_candidate_stats()
    
    subsystems = {
        # ...
        "candidate_pipeline": {
            "status": "degraded" if self.candidate_manager.degraded else "ok",
            "pending_candidate_count": candidate_stats["pending"],
            "high_risk_pending_count": candidate_stats["high_risk_pending"],
            "recent_reverted_count": candidate_stats["recent_reverted"],
        },
    }
```

### 10.2 暴露的指标

| 指标 | 说明 |
|------|------|
| `pending_candidate_count` | 待处理候选数量 |
| `high_risk_pending_count` | 高风险待审批数量 |
| `recent_reverted_count` | 最近回滚数量 |

---

## 11. 验证与验收

### 11.1 验证命令

```bash
# 候选管道专项测试
python -m pytest tests/test_evolution_pipeline.py \
  tests/test_personality_evolver.py \
  tests/test_relationship_memory.py \
  tests/test_runtime_bootstrap.py

# 完整测试套件
python -m pytest

# 字节码编译检查
python -m compileall app tests
```

### 11.2 验收检查项

- [ ] 82 个测试全部通过（Phase 17 的 77 + Phase 18 新增）
- [ ] `test_evolution_pipeline.py` 存在且覆盖关键路径
- [ ] EvolutionCandidate / Status / RiskLevel / AffectedArea 类型正确
- [ ] 候选管理器正确聚合和去重
- [ ] 低风险（>=2证据）自动应用
- [ ] 中风险（>=3证据 + >=2上下文）自动应用
- [ ] 高风险触发 HITL
- [ ] CognitionUpdater 提交候选而非直接写入
- [ ] PersonalityEvolver slow_evolve 改为候选机制
- [ ] drift 回滚标记候选为 reverted
- [ ] 双路径 HITL（memory_confirmation vs evolution_candidate）分离
- [ ] Journal 事件标准化
- [ ] `/health` 暴露候选管道指标
- [ ] 运行时正确注入候选管理器

### 11.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_evolution_pipeline.py` | Phase 18 新增，测试候选管道全生命周期 |
| `tests/test_personality_evolver.py` | 更新覆盖慢进化候选机制 |
| `tests/test_relationship_memory.py` | 更新 |
| `tests/test_runtime_bootstrap.py` | 更新运行时连接 |
| `tests/test_failure_semantics.py` | 更新 |
| `tests/test_observability.py` | 更新健康端点暴露 |

---

## 12. Explicitly Not Done Yet

以下功能在 Phase 18 中**仍未完成**：

- [ ] 持久化候选存储（当前仅为进程内存）
- [ ] world-model 候选的通用回滚引擎（仅有 journaled revert 状态 + 现有 superseded/conflicted 记忆轨迹）
- [ ] 可配置风险阈值（Phase 18 使用固定默认值）
- [ ] 用户-facing 治理 UI（浏览/审批候选历史）
- [ ] Phase 16 memory-confirmation 证据与 Phase 18 candidate 证据池的统一
- [ ] 冲突密集型推断记忆在进入高风险进化候选路径前仍优先使用现有 memory-confirmation gate

---

## 13. Phase 18 的意义

### 13.1 从"能进化"到"受控进化"

Phase 18 完成后，系统从"能进化"升级到"受控进化"：

```
Phase 17 之前
     ↓
进化信号 → 直接写入
     ↓
无审批，无风险分级

Phase 18 新增
     ↓
进化信号 → 候选管道 → 审批 → 应用
     ↓
风险分级 + HITL + 去重 + 生命周期
```

### 13.2 双路径 HITL 语义清晰

Phase 18 确立的双路径 HITL 机制：

```
记忆确认（memory_confirmation）
     ↓
语义：这是真的吗？
     ↓
用于：敏感/低置信度记忆

进化审批（evolution_candidate）
     ↓
语义：应该这样改变人格吗？
     ↓
用于：高风险人格/认知变化
```

### 13.3 为未来 Phase 奠定基础

Phase 18 建立的候选管道是后续 Phase 的基石：

- 持久化候选存储 → 基于当前内存结构扩展
- 可配置阈值 → 基于当前固定阈值扩展
- 候选治理 UI → 基于当前 Journal 事件
- 证据池统一 → 统一 memory_confirmation 和 evolution_candidate

### 13.4 关键设计原则

Phase 18 确立的关键设计原则：

| 原则 | 说明 |
|------|------|
| **候选优先** | 所有长期变化必须经过候选管道 |
| **风险分级** | low/medium/high 不同处理策略 |
| **双路径分离** | memory_confirmation ≠ evolution_candidate |
| **去重聚合** | 相同变更合并候选，避免冗余 |
| **Journal 标准化** | 候选生命周期事件统一记录格式 |
| **健康暴露** | 候选管道指标纳入运行时健康 |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-17-学习笔记]] — 人格稳定性与会话适应
- [[../phase_18_status.md|phase_18_status.md]] — Phase 18 给 Codex 的状态文档
