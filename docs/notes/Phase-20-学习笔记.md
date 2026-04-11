# Phase 20 学习笔记：关系状态机

> **前置阶段**：[[Phase-19-学习笔记]]  
> **目标**：建立显式关系阶段状态机，基于启发式规则派生关系阶段，通过候选管道控制阶段转换  
> **里程碑**：本阶段完成后系统具备关系阶段感知能力，支持基于信任的渐进式亲密

---

## 目录

- [概述](#概述)
- [1. Phase 20 文件清单](#1-phase-20-文件清单)
- [2. 为什么需要关系状态机](#2-为什么需要关系状态机)
- [3. RelationshipStageState 数据结构](#3-relationshipstagestate-数据结构)
- [4. 关系阶段枚举](#4-关系阶段枚举)
- [5. RelationshipStateMachine 设计](#5-relationshipstatemachine-设计)
- [6. 阶段派生启发式规则](#6-阶段派生启发式规则)
- [7. 阶段转换约束](#7-阶段转换约束)
- [8. CognitionUpdater 集成](#8-cognitionupdater-集成)
- [9. SoulEngine Prompt 更新](#9-soulinge-prompt-更新)
- [10. Journal 事件扩展](#10-journal-事件扩展)
- [11. 运行时连接](#11-运行时连接)
- [12. 验证与验收](#12-验证与验收)
- [13. Explicitly Not Done Yet](#13-explicitly-not-done-yet)
- [14. Phase 20 的意义](#14-phase-20-的意义)

---

## 概述

### 目标

Phase 20 的目标是**建立关系阶段状态机**，让系统具备：

- 显式关系阶段状态（unfamiliar / trust_building / stable_companion / vulnerable_support / repair_and_recovery）
- 基于启发式规则的关系阶段派生
- 阶段转换通过候选管道控制
- Prompt-facing 关系策略快照
- 信任渐进式增长支持

### Phase 19 到 Phase 20 的演进

Phase 19 建立了情感理解与支持策略，Phase 20 则关注**关系演进**：

```
Phase 19 完成时
     ↓
情感理解 + 支持偏好学习
     ↓
系统能识别用户情感和支持偏好
     ↓
但缺乏关系阶段感知
     ↓
     ↓
┌─────────────────────────────────────────┐
│  Phase 19 的关系缺失                      │
├─────────────────────────────────────────┤
│  • 无关系阶段概念                         │
│  • 无法感知关系深度                       │
│  • 信任建立无渐进性                       │
│  • 关系破裂无修复路径                     │
└─────────────────────────────────────────┘

Phase 20 新增
     ↓
关系阶段状态机
     ↓
unfamiliar → trust_building → stable_companion
     ↓
vulnerable_support（信任基础上的脆弱性支持）
     ↓
repair_and_recovery（破裂修复）
     ↓
Prompt 注入关系阶段上下文
```

### 新的系统形态

```
关系证据 → RelationshipStateMachine
     ↓
┌─────────────────────────────────────────┐
│  启发式阶段派生                          │
├─────────────────────────────────────────┤
│  unfamiliar                             │
│      ↓ (多次正面交互)                    │
│  trust_building                         │
│      ↓ (持续信任 + 脆弱性信号)           │
│  stable_companion                       │
│      ↓ (信任基础上 + 深度脆弱分享)       │
│  vulnerable_support                     │
│                                         │
│  rupture (冲突/误解)                     │
│      ↓                                   │
│  repair_and_recovery                     │
│      ↓ (修复后)                          │
│  回到 trust_building                    │
└─────────────────────────────────────────┘
     ↓
阶段转换通过候选管道
     ↓
Prompt 注入关系阶段提示
```

---

## 1. Phase 20 文件清单

| 文件 | 内容 |
|------|------|
| `app/memory/core_memory.py` | 新增 RelationshipStageState |
| `app/memory/core_memory_store.py` | 更新快照序列化，兼容旧格式 |
| `app/evolution/core_memory_scheduler.py` | 更新压缩保留 relationship_stage |
| `app/evolution/relationship_state_machine.py` | Phase 20 新增，关系状态机 |
| `app/evolution/cognition_updater.py` | 更新：阶段评估触发、阶段转换载荷 |
| `app/evolution/candidate_pipeline.py` | 扩展 journal details |
| `app/evolution/personality_evolver.py` | 暴露 apply_candidates() 辅助方法 |
| `app/soul/engine.py` | 更新 prompt 注入关系阶段 |
| `app/runtime/bootstrap.py` | 更新运行时连接 |
| `tests/test_relationship_state_machine.py` | Phase 20 新增测试 |

---

## 2. 为什么需要关系状态机

### 2.1 之前的问题

Phase 19 之前，系统缺乏关系阶段感知：

| 问题 | 描述 | 影响 |
|------|------|------|
| **无阶段概念** | 无法区分陌生、熟悉、亲密关系 | 回复风格单一 |
| **无信任渐进** | 一次性建立完整信任 | 越界风险 |
| **无脆弱性支持** | 无法识别深层信任后的脆弱分享 | 共情深度不足 |
| **无破裂修复** | 关系破裂无专门处理路径 | 修复效率低 |

### 2.2 关系状态机的价值

```
关系状态机 = 阶段感知 + 渐进信任 + 破裂修复

价值1: 边界安全
    ↓
unfamiliar 阶段强边界
     ↓
渐进放松，避免越界

价值2: 深度共情
    ↓
vulnerable_support 阶段识别深度信任
     ↓
更强的情感支持

价值3: 关系维护
    ↓
repair_and_recovery 专门处理破裂
     ↓
主动修复关系
```

---

## 3. RelationshipStageState 数据结构

### 3.1 定义

```python
@dataclass
class RelationshipStageState:
    """关系阶段状态"""
    
    stage: RelationshipStage          # 当前阶段
    confidence: float                   # 阶段置信度 0.0-1.0
    updated_at: datetime              # 更新时间
    entered_at: datetime              # 进入当前阶段时间
    
    # 脆弱性支持能力
    supports_vulnerability: bool      # 是否支持深度脆弱性
    
    # 是否需要修复
    repair_needed: bool              # 当前是否需要关系修复
    
    # 最近转换原因
    recent_transition_reason: str | None  # 最近阶段转换原因
    
    # 最近共享事件（prompt-facing）
    recent_shared_events: list[str]   # 最近共享事件摘要
```

### 3.2 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `stage` | RelationshipStage | 当前阶段枚举值 |
| `confidence` | float | 阶段置信度 |
| `updated_at` | datetime | 状态更新时间 |
| `entered_at` | datetime | 进入该阶段的时间 |
| `supports_vulnerability` | bool | 是否支持深度脆弱性分享 |
| `repair_needed` | bool | 是否需要关系修复 |
| `recent_transition_reason` | str | 最近的阶段转换原因 |
| `recent_shared_events` | list[str] | 最近共享事件（微小，prompt-facing） |

---

## 4. 关系阶段枚举

### 4.1 五阶段定义

```python
class RelationshipStage:
    UNFAMILIAR = "unfamiliar"              # 陌生阶段
    TRUST_BUILDING = "trust_building"       # 信任建立中
    STABLE_COMPANION = "stable_companion"  # 稳定陪伴
    VULNERABLE_SUPPORT = "vulnerable_support"  # 脆弱性支持
    REPAIR_AND_RECOVERY = "repair_and_recovery"  # 修复与恢复
```

### 4.2 各阶段含义

| 阶段 | 含义 | 支持脆弱性 | 边界策略 |
|------|------|-----------|---------|
| `unfamiliar` | 初始/陌生阶段 | 否 | 强边界 |
| `trust_building` | 信任建立中 | 有限 | 中等边界 |
| `stable_companion` | 稳定陪伴关系 | 是 | 适度放松 |
| `vulnerable_support` | 深度信任支持 | 完全 | 最小边界 |
| `repair_and_recovery` | 关系修复中 | 有限 | 恢复边界 |

### 4.3 脆弱性支持能力

```python
VULNERABILITY_SUPPORT_MAP = {
    RelationshipStage.UNFAMILIAR: False,           # 不支持
    RelationshipStage.TRUST_BUILDING: False,        # 有限支持
    RelationshipStage.STABLE_COMPANION: True,      # 支持
    RelationshipStage.VULNERABLE_SUPPORT: True,     # 完全支持
    RelationshipStage.REPAIR_AND_RECOVERY: False,   # 有限支持（修复中）
}
```

---

## 5. RelationshipStateMachine 设计

### 5.1 状态机职责

```python
class RelationshipStateMachine:
    """
    关系状态机
    - 启发式、确定性
    - 无 ML 模型调用
    - 单元测试友好
    """
    
    def __init__(
        self,
        core_memory_cache: CoreMemoryCache,
        candidate_manager: EvolutionCandidateManager,
    ) -> None:
        self.core_memory_cache = core_memory_cache
        self.candidate_manager = candidate_manager
    
    async def evaluate(
        self,
        user_id: str,
        current_observation: dict | None = None,
    ) -> RelationshipStageState:
        """
        评估当前关系阶段
        - 读取持久关系证据
        - 接受当前观察提示
        - 派生推荐阶段
        """
        ...
    
    def derive_stage(
        self,
        evidence: RelationshipEvidence,
        current_hint: dict | None,
    ) -> tuple[RelationshipStage, float, str]:
        """
        派生阶段
        返回: (阶段, 置信度, 转换原因)
        """
        ...
```

### 5.2 RelationshipEvidence

```python
@dataclass
class RelationshipEvidence:
    """关系证据"""
    
    positive_interactions: int       # 正面交互次数
    negative_interactions: int      # 负面交互次数
    vulnerability_shares: int       # 脆弱性分享次数
    trust_signals: list[str]       # 信任信号列表
    rupture_signals: list[str]     # 破裂信号列表
    duration_days: int             # 关系持续天数
    shared_experiences: list[str]  # 共享经历
```

### 5.3 阶段评估流程

```python
async def evaluate(
    self,
    user_id: str,
    current_observation: dict | None = None,
) -> RelationshipStageState:
    """评估当前关系阶段"""
    
    # 1. 读取现有阶段
    current_state = await self.core_memory_cache.get_relationship_stage(user_id)
    current_stage = current_state.stage if current_state else RelationshipStage.UNFAMILIAR
    
    # 2. 读取关系证据
    evidence = await self._load_relationship_evidence(user_id)
    
    # 3. 合并当前观察提示
    if current_observation:
        evidence = self._merge_observation(evidence, current_observation)
    
    # 4. 派生新阶段
    new_stage, confidence, reason = self.derive_stage(evidence, current_observation)
    
    # 5. 检查是否需要阶段转换
    if new_stage != current_stage:
        # 通过候选管道提交转换
        await self._submit_stage_transition(
            user_id=user_id,
            from_stage=current_stage,
            to_stage=new_stage,
            reason=reason,
            evidence=evidence,
        )
    
    # 6. 构建新状态
    new_state = RelationshipStageState(
        stage=new_stage,
        confidence=confidence,
        updated_at=utc_now(),
        entered_at=current_state.entered_at if new_stage == current_stage else utc_now(),
        supports_vulnerability=VULNERABILITY_SUPPORT_MAP[new_stage],
        repair_needed=new_stage == RelationshipStage.REPAIR_AND_RECOVERY,
        recent_transition_reason=reason if new_stage != current_stage else current_state.recent_transition_reason,
        recent_shared_events=self._build_recent_events(evidence),
    )
    
    return new_state
```

---

## 6. 阶段派生启发式规则

### 6.1 转换规则

```python
STAGE_TRANSITION_RULES = {
    # 阶段 -> (目标条件, 目标阶段)
    RelationshipStage.UNFAMILIAR: {
        "positive_interactions >= 3": RelationshipStage.TRUST_BUILDING,
    },
    
    RelationshipStage.TRUST_BUILDING: {
        "positive_interactions >= 5 AND duration_days >= 7": RelationshipStage.STABLE_COMPANION,
        "vulnerability_shares >= 2 AND trust_signals >= 3": RelationshipStage.VULNERABLE_SUPPORT,
        "negative_interactions >= 1 OR rupture_signals >= 1": RelationshipStage.REPAIR_AND_RECOVERY,
    },
    
    RelationshipStage.STABLE_COMPANION: {
        "vulnerability_shares >= 1 AND trust_signals >= 2": RelationshipStage.VULNERABLE_SUPPORT,
        "negative_interactions >= 1 OR rupture_signals >= 1": RelationshipStage.REPAIR_AND_RECOVERY,
    },
    
    RelationshipStage.VULNERABLE_SUPPORT: {
        "negative_interactions >= 1 OR rupture_signals >= 1": RelationshipStage.REPAIR_AND_RECOVERY,
    },
    
    RelationshipStage.REPAIR_AND_RECOVERY: {
        "positive_interactions >= 2 AND trust_signals >= 1": RelationshipStage.TRUST_BUILDING,
    },
}


def derive_stage(
    self,
    evidence: RelationshipEvidence,
    current_hint: dict | None,
) -> tuple[RelationshipStage, float, str]:
    """派生关系阶段"""
    
    current = self._get_current_stage()
    
    # 1. 检查破裂/修复信号（最高优先级）
    if evidence.rupture_signals or evidence.negative_interactions > 0:
        if current != RelationshipStage.REPAIR_AND_RECOVERY:
            return (
                RelationshipStage.REPAIR_AND_RECOVERY,
                0.8,
                "rupture_detected",
            )
    
    # 2. 检查修复恢复条件
    if current == RelationshipStage.REPAIR_AND_RECOVERY:
        if evidence.positive_interactions >= 2 and evidence.trust_signals:
            return (
                RelationshipStage.TRUST_BUILDING,
                0.7,
                "recovery_complete",
            )
    
    # 3. 检查脆弱性升级条件
    if evidence.vulnerability_shares >= 2 and evidence.trust_signals:
        if current == RelationshipStage.TRUST_BUILDING:
            return (
                RelationshipStage.VULNERABLE_SUPPORT,
                0.75,
                "vulnerability_trust_established",
            )
        elif current == RelationshipStage.STABLE_COMPANION:
            return (
                RelationshipStage.VULNERABLE_SUPPORT,
                0.8,
                "deep_vulnerability_shared",
            )
    
    # 4. 检查稳定陪伴条件
    if evidence.positive_interactions >= 5 and evidence.duration_days >= 7:
        if current in {RelationshipStage.UNFAMILIAR, RelationshipStage.TRUST_BUILDING}:
            return (
                RelationshipStage.STABLE_COMPANION,
                0.8,
                "stable_trust_established",
            )
    
    # 5. 检查信任建立条件
    if evidence.positive_interactions >= 3:
        if current == RelationshipStage.UNFAMILIAR:
            return (
                RelationshipStage.TRUST_BUILDING,
                0.7,
                "initial_trust_building",
            )
    
    # 6. 默认保持当前阶段
    return (current, 1.0, "no_change")
```

### 6.2 关键约束

```python
STAGE_CONSTRAINTS = {
    # 不允许单次正面交互跳转到 stable_companion
    "no_single_jump_to_stable": True,
    
    # vulnerable_support 只能在信任基础上
    "vulnerable_requires_trust": True,
    
    # repair_and_recovery 优先级高于普通正向
    "repair_priority_over_positive": True,
}
```

---

## 7. 阶段转换约束

### 7.1 渐进信任约束

```python
def _can_transition_to(
    self,
    current: RelationshipStage,
    target: RelationshipStage,
    evidence: RelationshipEvidence,
) -> tuple[bool, str]:
    """检查是否可以转换到目标阶段"""
    
    # 约束1: 不允许从 unfamiliar 直接跳到 stable_companion
    if current == RelationshipStage.UNFAMILIAR:
        if target == RelationshipStage.STABLE_COMPANION:
            return False, "must_pass_through_trust_building"
    
    # 约束2: vulnerable_support 需要信任基础
    if target == RelationshipStage.VULNERABLE_SUPPORT:
        if current not in {RelationshipStage.TRUST_BUILDING, RelationshipStage.STABLE_COMPANION}:
            return False, "requires_trust_base"
        
        if not evidence.trust_signals:
            return False, "insufficient_trust_signals"
    
    # 约束3: repair_and_recovery 可从任何非自身的阶段进入
    if target == RelationshipStage.REPAIR_AND_RECOVERY:
        return True, "rupture_detected"
    
    # 约束4: 从 repair_and_recovery 恢复只能回到 trust_building
    if current == RelationshipStage.REPAIR_AND_RECOVERY:
        if target != RelationshipStage.TRUST_BUILDING:
            return False, "recovery_must_return_to_trust_building"
    
    return True, "allowed"
```

### 7.2 阶段行为提示

```python
STAGE_BEHAVIOR_HINTS = {
    RelationshipStage.UNFAMILIAR: {
        "tone": "respectful_distance",
        "boundary_strength": 0.9,
        "warmth": 0.3,
        "hint": "保持专业和适当距离",
    },
    RelationshipStage.TRUST_BUILDING: {
        "tone": "warm_but_careful",
        "boundary_strength": 0.7,
        "warmth": 0.5,
        "hint": "温暖但谨慎，逐步建立信任",
    },
    RelationshipStage.STABLE_COMPANION: {
        "tone": "comfortable",
        "boundary_strength": 0.5,
        "warmth": 0.7,
        "hint": "舒适稳定的关系，可以更放松",
    },
    RelationshipStage.VULNERABLE_SUPPORT: {
        "tone": "deeply_supportive",
        "boundary_strength": 0.3,
        "warmth": 0.9,
        "hint": "深度信任关系，提供深度情感支持",
    },
    RelationshipStage.REPAIR_AND_RECOVERY: {
        "tone": "repair_focused",
        "boundary_strength": 0.8,
        "warmth": 0.4,
        "hint": "关系修复中，保持支持但谨慎",
    },
}
```

---

## 8. CognitionUpdater 集成

### 8.1 阶段评估触发

Phase 20 的 CognitionUpdater 在以下情况触发关系阶段评估：

```python
async def handle_lesson_generated(self, event: Event) -> None:
    lesson = event.payload["lesson"]
    
    # 处理 lesson（Phase 18/19 逻辑）
    await self._process_lesson(lesson)
    
    # Phase 20 新增：触发关系阶段评估
    if lesson.is_world_model:
        await self._trigger_relationship_evaluation(
            user_id=lesson.user_id,
            observation={
                "type": "world_model_lesson",
                "lesson": lesson,
            },
        )


async def _trigger_relationship_evaluation(
    self,
    user_id: str,
    observation: dict,
) -> None:
    """触发关系阶段评估"""
    
    # 合并到候选评估
    stage_state = await self.relationship_state_machine.evaluate(
        user_id=user_id,
        current_observation=observation,
    )
    
    # 更新 core memory
    await self.core_memory_scheduler.update_relationship_stage(
        user_id=user_id,
        stage_state=stage_state,
    )
```

### 8.2 HITL 确认后触发

```python
async def handle_hitl_feedback(self, task_id: str, decision: str, metadata: dict) -> None:
    """处理 HITL 反馈"""
    
    # ... Phase 18/19 逻辑 ...
    
    # Phase 20 新增：HITL 确认后重新评估关系阶段
    if metadata.get("memory_confirmation"):
        await self._trigger_relationship_evaluation(
            user_id=metadata["user_id"],
            observation={
                "type": "hitl_confirmation",
                "decision": decision,
                "metadata": metadata,
            },
        )
```

### 8.3 阶段转换载荷

Phase 20 扩展了候选管道的 journal details：

```python
RELATIONSHIP_CANDIDATE_DETAILS = {
    "relationship_stage_from": str,   # 原阶段
    "relationship_stage_to": str,     # 目标阶段
    "transition_reason": str,        # 转换原因
}
```

---

## 9. SoulEngine Prompt 更新

### 9.1 Prompt 注入

Phase 20 的 SoulEngine 在 prompt 中注入关系阶段：

```
## Relationship Stage
Current Stage: stable_companion
Confidence: 0.8
Recent Transition: stable_trust_established (3 days ago)
Supports Vulnerability: Yes

Behavior Hint: 舒适稳定的关系，可以更放松
Recent Shared Events: ["讨论工作挑战", "分享周末计划"]
```

### 9.2 格式化函数

```python
def _format_relationship_stage(self, state: RelationshipStageState) -> str:
    """格式化关系阶段为 prompt 文本"""
    
    if not state:
        return "## Relationship Stage\n- Not established"
    
    hint = STAGE_BEHAVIOR_HINTS.get(state.stage, {})
    
    lines = [
        "## Relationship Stage",
        f"Current Stage: {state.stage.value}",
        f"Confidence: {state.confidence:.2f}",
    ]
    
    if state.recent_transition_reason:
        lines.append(f"Recent Transition: {state.recent_transition_reason}")
    
    lines.append(f"Supports Vulnerability: {'Yes' if state.supports_vulnerability else 'No'}")
    
    if hint:
        lines.append(f"\nBehavior Hint: {hint.get('hint', '')}")
    
    if state.recent_shared_events:
        lines.append(f"\nRecent Shared Events:")
        for event in state.recent_shared_events[:3]:  # 限制3条
            lines.append(f"- {event}")
    
    return "\n".join(lines)
```

---

## 10. Journal 事件扩展

### 10.1 阶段转换事件

Phase 20 新增了关系阶段转换事件：

```python
class EventType:
    # ... Phase 18/19 事件 ...
    RELATIONSHIP_STAGE_TRANSITION_APPLIED = "relationship_stage_transition_applied"
```

### 10.2 Journal Details

```python
RELATIONSHIP_TRANSITION_JOURNAL = {
    "event_type": "relationship_stage_transition_applied",
    "details": {
        "relationship_stage_from": str,
        "relationship_stage_to": str,
        "transition_reason": str,
        "confidence": float,
        "candidate_id": str,
    },
}
```

---

## 11. 运行时连接

### 11.1 Bootstrap 更新

Phase 20 的运行时连接：

```python
async def bootstrap_runtime() -> RuntimeContext:
    # ... Phase 19 组件 ...
    
    # Phase 20 新增：关系状态机
    relationship_state_machine = RelationshipStateMachine(
        core_memory_cache=core_memory_cache,
        candidate_manager=candidate_manager,
    )
    
    # 注入到 CognitionUpdater
    cognition_updater = CognitionUpdater(
        # ...
        relationship_state_machine=relationship_state_machine,
    )
    
    return RuntimeContext(
        # ...
        relationship_state_machine=relationship_state_machine,
    )
```

### 11.2 健康快照扩展

```python
def health_snapshot(self) -> dict[str, Any]:
    subsystems = {
        # ...
        "relationship_state_machine": {
            "status": "ok",
            "relationship_stage_enabled": True,
            "relationship_stage_degraded": self.relationship_state_machine.degraded,
            "current_stage": self._get_current_stage(),
        },
    }
```

---

## 12. 验证与验收

### 12.1 验证命令

```bash
# Phase 20 专项测试
python -m pytest tests/test_relationship_state_machine.py \
  tests/test_relationship_memory.py \
  tests/test_soul_engine.py \
  tests/test_runtime_bootstrap.py

# 完整测试套件
python -m pytest

# 字节码编译检查
python -m compileall app tests
```

### 12.2 验收检查项

- [ ] 96 个测试全部通过（Phase 19 的 90 + Phase 20 新增）
- [ ] `test_relationship_state_machine.py` 存在且覆盖关键路径
- [ ] RelationshipStageState 数据结构正确
- [ ] 五阶段枚举正确定义
- [ ] 启发式派生规则覆盖所有转换路径
- [ ] 阶段转换约束正确实施
- [ ] vulnerable_support 只能在信任基础上
- [ ] repair_and_recovery 可从任何非自身阶段进入
- [ ] CognitionUpdater 正确触发阶段评估
- [ ] 候选管道正确处理阶段转换
- [ ] SoulEngine prompt 正确注入关系阶段
- [ ] Journal 事件正确记录
- [ ] 运行时健康快照正确暴露
- [ ] 旧快照向后兼容（unfamiliar + 0.0 confidence）

### 12.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_relationship_state_machine.py` | Phase 20 新增，测试阶段派生、转换约束、候选提交 |

---

## 13. Explicitly Not Done Yet

以下功能在 Phase 20 中**仍未完成**：

- [ ] 用户-facing 关系阶段 UI 或手动覆盖面
- [ ] 专用 `/relationship` 端点或阶段检查端点
- [ ] 超越有限修复/误解启发式的更丰富破裂 taxonomy
- [ ] 利用关系阶段主动发起外展的主动行为引擎
- [ ] 超越微小 `recent_shared_events` prompt 摘要的长期事件汇总器

---

## 14. Phase 20 的意义

### 14.1 从"懂情感"到"懂关系"

Phase 20 完成后，系统从"懂情感"升级到"懂关系"：

```
Phase 19 之前
     ↓
情感理解 + 支持偏好
     ↓
能识别用户情感
     ↓
但关系是静态的

Phase 20 新增
     ↓
关系阶段状态机
     ↓
unfamiliar → trust_building → stable_companion
     ↓
vulnerable_support / repair_and_recovery
     ↓
关系渐进演进
```

### 14.2 信任渐进式增长

Phase 20 确立了信任渐进式增长机制：

```
信任不能一蹴而就
     ↓
unfamiliar 强边界
     ↓
trust_building 中等放松
     ↓
stable_companion 舒适
     ↓
vulnerable_support 深度
     ↓
防止关系越界
```

### 14.3 为未来 Phase 奠定基础

Phase 20 建立的关系状态机是后续 Phase 的基石：

- 关系阶段 UI → 基于当前阶段状态
- 主动外展 → 基于阶段感知
- 更丰富破裂模型 → 基于当前有限修复
- 长期事件汇总 → 基于 recent_shared_events 扩展

### 14.4 关键设计原则

Phase 20 确立的关键设计原则：

| 原则 | 说明 |
|------|------|
| **启发式派生** | 确定性规则，非 ML 模型 |
| **候选管道** | 阶段转换必须通过候选管道 |
| **信任渐进** | 不允许跳阶段 |
| **破裂优先** | repair_and_recovery 优先级最高 |
| **阶段分离** | relationship_stage ≠ relationship_style |
| **prompt-facing** | recent_shared_events 微小，不新增持久化 |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-19-学习笔记]] — 情感理解与支持策略
- [[../phase_20_status.md|phase_20_status.md]] — Phase 20 给 Codex 的状态文档
