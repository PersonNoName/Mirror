# Phase 17 学习笔记：人格稳定性与会话适应

> **前置阶段**：[[Phase-16-学习笔记]]  
> **目标**：重构人格状态为显式分层结构，建立版本化和回滚机制，区分快适应与慢进化  
> **里程碑**：本阶段完成后人格系统具备版本控制、回滚能力和显式的短/长期人格区分

---

## 目录

- [概述](#概述)
- [1. Phase 17 文件清单](#1-phase-17-文件清单)
- [2. 为什么需要人格分层](#2-为什么需要人格分层)
- [3. 新的 PersonalityState 分层结构](#3-新的-personalitystate-分层结构)
- [4. 稳定长期身份结构](#4-稳定长期身份结构)
- [5. 关系风格结构](#5-关系风格结构)
- [6. 会话适应结构](#6-会话适应结构)
- [7. 版本化快照机制](#7-版本化快照机制)
- [8. PersonalityEvolver 重写](#8-personalityevolver-重写)
- [9. 漂移检测多因素化](#9-漂移检测多因素化)
- [10. SoulEngine Prompt 更新](#10-soulinge-prompt-更新)
- [11. CoreMemoryStore 向后兼容](#11-corememorystore-向后兼容)
- [12. 验证与验收](#12-验证与验收)
- [13. Explicitly Not Done Yet](#13-explicitly-not-done-yet)
- [14. Phase 17 的意义](#14-phase-17-的意义)

---

## 概述

### 目标

Phase 17 的目标是**建立人格稳定性机制**，让系统具备：

- 人格状态显式分层（core / relationship_style / session_adaptation）
- 人格版本化和回滚能力
- 快适应（短期会话）与慢进化（长期人格）分离
- 多因素漂移检测
- 会话适应明确标记为短期

### Phase 16 到 Phase 17 的演进

Phase 16 建立了关系记忆基础，Phase 17 则关注人格稳定性：

```
Phase 16 完成时
     ↓
记忆系统具备 truth-aware 能力
     ↓
事实/推断/关系记忆区分清晰
     ↓
但人格系统仍存在问题：
     ↓
     ↓
┌─────────────────────────────────────────┐
│  Phase 16 的人格问题                      │
├─────────────────────────────────────────┤
│  • 人格 flat 结构，无分层                 │
│  • 无版本化，快照只是追加                 │
│  • fast_adapt 可直接修改长期人格          │
│  • 漂移检测仅基于规则数量                 │
│  • 会话适应与长期人格边界模糊             │
└─────────────────────────────────────────┘

Phase 17 新增
     ↓
人格三层结构：core / relationship_style / session
     ↓
版本化快照 + 回滚机制
     ↓
fast_adapt() 仅修改短期会话适应
     ↓
slow_evolve() 需重复证据才修改长期人格
     ↓
多因素漂移检测
```

### 新的系统形态

```
人格状态分层
     ↓
┌─────────────────────────────────────────┐
│  PersonalityState                        │
├─────────────────────────────────────────┤
│  core_personality (Stable Identity)     │
│    - baseline_description               │
│    - behavioral_rules (persistent)       │
│    - traits_internal                    │
│    - stable_fields                       │
│    - updated_at                         │
├─────────────────────────────────────────┤
│  relationship_style (Long-term Style)    │
│    - warmth                             │
│    - boundary_strength                  │
│    - supportiveness                     │
│    - humor                              │
│    - preferred_closeness                │
├─────────────────────────────────────────┤
│  session_adaptation (Short-term)        │
│    - current items                       │
│    - session_id                         │
│    - created/expires timestamps          │
│    - max_item_count                     │
└─────────────────────────────────────────┘
     ↓
版本化快照
     ↓
┌─────────────────────────────────────────┐
│  SnapshotRecord                          │
├─────────────────────────────────────────┤
│  - version                              │
│  - snapshot_version                     │
│  - last_snapshot_at                     │
│  - rollback_count                       │
│  - snapshot_refs                        │
└─────────────────────────────────────────┘
```

---

## 1. Phase 17 文件清单

| 文件 | 内容 |
|------|------|
| `app/memory/core_memory.py` | 重构 PersonalityState 为三层结构 |
| `app/memory/core_memory_store.py` | 扩展序列化/反序列化，支持旧快照兼容 |
| `app/evolution/personality_evolver.py` | 重写 fast_adapt/slow_evolve，版本化快照 |
| `app/stability/snapshot.py` | 升级为版本化快照记录 |
| `app/soul/engine.py` | 更新 prompt 构建，分离三层人格 |
| `app/evolution/core_memory_scheduler.py` | 更新人格 token 截断处理 |
| `tests/test_personality_evolver.py` | Phase 17 新增测试 |
| `tests/test_soul_engine.py` | 更新覆盖人格分层 prompt |
| `tests/conftest.py` | 更新人格相关 fixtures |

---

## 2. 为什么需要人格分层

### 2.1 之前的问题

Phase 16 之前，人格系统存在以下问题：

| 问题 | 描述 | 影响 |
|------|------|------|
| **Flat 结构** | 人格所有字段混在一起 | 难以区分长期/短期属性 |
| **无版本化** | 快照只是追加，无版本控制 | 无法回滚到特定版本 |
| **fast_adapt 越权** | fast_adapt 可直接修改长期人格 | 短期信号意外改变人格 |
| **漂移检测单一** | 仅基于规则数量判断漂移 | 漏判其他维度的人格漂移 |
| **会话适应模糊** | 会话适应与长期人格边界不清 | 推理时可能混淆 |

### 2.2 分层设计的价值

```
人格分层 = 稳定身份 + 关系风格 + 会话适应

价值1: 稳定性
    ↓
核心人格稳定，不因短期信号改变
    ↓
用户感受到一致的人格

价值2: 可追溯
    ↓
版本化快照 + 回滚机制
    ↓
人格演变有迹可循

价值3: 漂移可检测
    ↓
多因素漂移检测
    ↓
规则增量 + 特质增量 + 关系风格增量 + 空baseline检测

价值4: 会话隔离
    ↓
会话适应明确标记为短期
    ↓
不影响长期人格
```

---

## 3. 新的 PersonalityState 分层结构

### 3.1 三层架构

```python
@dataclass
class PersonalityState:
    """人格状态 - 三层结构"""
    
    # Layer 1: 核心人格（稳定长期身份）
    core_personality: CorePersonality
    
    # Layer 2: 关系风格（长期但可缓慢演变）
    relationship_style: RelationshipStyle
    
    # Layer 3: 会话适应（短期，当前会话有效）
    session_adaptation: SessionAdaptation
    
    # 版本化元数据
    version: int = 1
    snapshot_version: int = 0
    last_snapshot_at: datetime | None = None
    rollback_count: int = 0
    snapshot_refs: list[str] = field(default_factory=list)
```

### 3.2 各层职责

| 层级 | 职责 | 演变速度 | 持久化 |
|------|------|---------|--------|
| core_personality | 基准描述、行为规则、核心特质 | 极慢（需重复证据） | PostgreSQL snapshot |
| relationship_style | 温暖度、边界强度、支持性等 | 慢（需多次验证） | PostgreSQL snapshot |
| session_adaptation | 当前会话的短期适应 | 仅当前会话 | SessionContextStore |

---

## 4. 稳定长期身份结构

### 4.1 CorePersonality 定义

```python
@dataclass
class CorePersonality:
    """核心人格 - 稳定长期身份"""
    
    baseline_description: str  # 基准人格描述（自然语言）
    
    behavioral_rules: list[BehavioralRule]  # 行为规则（持久化）
    
    traits_internal: dict[str, float]  # 内部特质（数值地图）
    
    stable_fields: dict[str, Any]  # 其他稳定字段
    
    updated_at: datetime  # 最后更新时间
```

### 4.2 稳定字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `baseline_description` | str | 人格基准描述，供 SoulEngine prompt 使用 |
| `behavioral_rules` | list[BehavioralRule] | 从交互中学习的行为规则，持久化存储 |
| `traits_internal` | dict[str, float] | 内部特质数值地图（不直接暴露给模型） |
| `stable_fields` | dict[str, Any] | 其他需要保持稳定的字段 |
| `updated_at` | datetime | 最后更新时间 |

### 4.3 行为规则持久化

Phase 17 明确 `behavioral_rules` 为持久化字段：

```python
@dataclass
class BehavioralRule:
    """行为规则"""
    rule: str                    # 规则内容（自然语言）
    source: str                  # 来源：user_feedback / observed_behavior / inferred
    confidence: float            # 置信度
    created_at: datetime         # 创建时间
    times_activated: int = 0     # 激活次数
    last_activated_at: datetime | None = None
```

---

## 5. 关系风格结构

### 5.1 RelationshipStyle 定义

Phase 17 引入了最小化的 `RelationshipStyle` 结构：

```python
@dataclass
class RelationshipStyle:
    """关系风格 - 长期但可缓慢演变"""
    
    warmth: float = 0.5           # 温暖度 0.0-1.0
    boundary_strength: float = 0.5  # 边界强度 0.0-1.0
    supportiveness: float = 0.5    # 支持性 0.0-1.0
    humor: float = 0.5            # 幽默感 0.0-1.0
    preferred_closeness: float = 0.5  # 偏好亲密度 0.0-1.0
    
    updated_at: datetime | None = None
```

### 5.2 关系风格字段说明

| 字段 | 说明 | 取值范围 |
|------|------|---------|
| `warmth` | 表达温暖和亲近的程度 | 0.0（冷淡）- 1.0（热情） |
| `boundary_strength` | 保持边界和隐私的程度 | 0.0（无边界）- 1.0（强边界） |
| `supportiveness` | 提供情感/实际支持的程度 | 0.0（中立）- 1.0（高度支持） |
| `humor` | 使用幽默的程度 | 0.0（严肃）- 1.0（高幽默） |
| `preferred_closeness` | 偏好的人际距离 | 0.0（疏远）- 1.0（亲密） |

### 5.3 有界演变

关系风格的演变**有界**：

```python
STYLE_CHANGE_BOUNDS = {
    "warmth": {"min": 0.3, "max": 0.9},           # 温暖度不极端化
    "boundary_strength": {"min": 0.2, "max": 0.8}, # 边界不消失
    "supportiveness": {"min": 0.4, "max": 1.0},   # 始终保持一定支持
    "humor": {"min": 0.0, "max": 0.7},            # 幽默不失控
    "preferred_closeness": {"min": 0.2, "max": 0.8}, # 亲密度保持合理
}
```

---

## 6. 会话适应结构

### 6.1 SessionAdaptation 定义

Phase 17 明确了 `SessionAdaptation` 的短期性质：

```python
@dataclass
class SessionAdaptation:
    """会话适应 - 短期，当前会话有效"""
    
    current_items: list[str]  # 当前会话的适应项
    
    session_id: str | None    # 关联的会话ID
    
    created_at: datetime      # 创建时间
    
    expires_at: datetime     # 过期时间
    
    max_item_count: int = 10  # 最大项数限制
```

### 6.2 短期性质保证

```python
# SessionAdaptation 明确短期
SESSION_ADAPTATION_TTL = timedelta(hours=24)

# 写入时
async def fast_adapt(self, signal: InteractionSignal) -> None:
    adaptation = SessionAdaptation(
        current_items=[signal.content],  # 当前会话有效
        session_id=signal.session_id,
        created_at=utc_now(),
        expires_at=utc_now() + SESSION_ADAPTATION_TTL,
    )
    
    # 仅写入 SessionContextStore，不写入 CoreMemoryStore
    await self.session_context_store.set_adaptations(
        user_id=signal.user_id,
        session_id=signal.session_id,
        adaptations=[signal.content],
    )
```

### 6.3 与长期人格的隔离

```
fast_adapt() 只修改 SessionAdaptation
     ↓
写入 SessionContextStore（Redis）
     ↓
不修改 core_personality
     ↓
不修改 relationship_style
     ↓
SoulEngine 标记为 "temporary and current-session-only"
```

---

## 7. 版本化快照机制

### 7.1 之前：追加式快照

Phase 16 的快照只是追加：

```python
# 旧逻辑
async def save_snapshot(self, personality: PersonalityState) -> None:
    # 只是追加新快照，不管理版本
    await self.db.execute(
        "INSERT INTO personality_snapshots (data) VALUES ($1)",
        json.dumps(asdict(personality))
    )
```

### 7.2 现在：版本化快照记录

Phase 17 的 SnapshotStore 升级为版本化：

```python
@dataclass
class SnapshotRecord:
    """快照记录 - 版本化"""
    version: int                  # 人格版本号
    snapshot_version: int         # 快照版本号
    data: dict                   # 快照数据
    reason: str                  # 创建原因：scheduled / evolution / rollback / manual
    created_at: datetime          # 创建时间
    rollback_count: int = 0       # 回滚次数


class PersonalitySnapshotStore:
    async def save(
        self,
        personality: PersonalityState,
        reason: str = "scheduled"
    ) -> SnapshotRecord:
        """保存新快照，返回快照记录"""
        record = SnapshotRecord(
            version=personality.version,
            snapshot_version=personality.snapshot_version + 1,
            data=asdict(personality),
            reason=reason,
            created_at=utc_now(),
        )
        await self._save_record(record)
        return record
    
    async def latest(self) -> SnapshotRecord | None:
        """获取最新快照"""
        ...
    
    async def rollback(self, target_version: int) -> PersonalityState:
        """回滚到指定版本"""
        ...
    
    async def get_version(self, version: int) -> SnapshotRecord | None:
        """获取指定版本的快照"""
        ...
    
    async def list_records(self) -> list[SnapshotRecord]:
        """列出所有快照记录"""
        ...
```

### 7.3 快照创建时机

Phase 17 明确了快照创建时机：

| 时机 | reason | 说明 |
|------|--------|------|
| 定期 | `scheduled` | 每日凌晨调度 |
| 进化前 | `evolution` | slow_evolve() 修改长期人格前 |
| 回滚前 | `rollback` | 回滚操作前保存当前状态 |
| 手动 | `manual` | 用户手动触发 |

---

## 8. PersonalityEvolver 重写

### 8.1 fast_adapt() vs slow_evolve()

Phase 17 重写了 PersonalityEvolver，明确分离快慢路径：

```python
class PersonalityEvolver:
    async def fast_adapt(self, signal: InteractionSignal) -> None:
        """
        快适应 - 仅修改短期会话适应
        不修改 core_personality
        不修改 relationship_style
        """
        # 仅写入 SessionContextStore
        await self.session_context_store.append_adaptation(
            user_id=signal.user_id,
            session_id=signal.session_id,
            adaptation=signal.content,
        )
    
    async def slow_evolve(self, signals: list[InteractionSignal]) -> None:
        """
        慢进化 - 仅在重复证据积累后修改长期人格
        需要多次验证才触发
        修改前先创建快照
        """
        # 1. 聚合信号，检测重复模式
        repeated_patterns = self._detect_repeated_patterns(signals)
        
        for pattern in repeated_patterns:
            # 2. 检查是否满足进化条件（重复次数阈值）
            if pattern.repeat_count >= REPEAT_THRESHOLD:
                # 3. 创建快照
                await self.snapshot_store.save(
                    self.core_memory_cache.get(personality),
                    reason="evolution"
                )
                
                # 4. 应用变化
                await self._apply_long_term_change(pattern)
                
                # 5. 检查漂移
                if self._detect_drift():
                    await self._rollback()
```

### 8.2 规则晋升要求

Phase 17 明确了规则晋升的要求：

```python
RULE_PROMOTION_REQUIREMENTS = {
    "min_repeat_count": 3,           # 至少3次重复信号
    "min_confidence": 0.7,           # 置信度 >= 0.7
    "session_span": 2,               # 跨至少2个会话
    "no_conflicting_signals": True,  # 无冲突信号
}
```

### 8.3 回滚机制

Phase 17 的回滚机制：

```python
async def _rollback(self) -> None:
    """回滚到最新保存的快照"""
    # 1. 获取最新快照
    latest = await self.snapshot_store.latest()
    
    if latest:
        # 2. 恢复人格状态
        restored = await self.snapshot_store.rollback(latest.version)
        
        # 3. 更新人格版本
        restored.rollback_count += 1
        restored.last_snapshot_at = utc_now()
        
        # 4. 刷新缓存
        await self.core_memory_cache.set(restored)
        
        # 5. 单独记录回滚事件到 journal
        await self.evolution_journal.record_rollback(
            previous_version=latest.version,
            reason="drift_detected",
            snapshot_ref=latest.snapshot_refs[-1] if latest.snapshot_refs else None,
        )
```

### 8.4 回滚与进化的日志分离

Phase 17 明确回滚事件与正常进化事件**分开记录**：

```python
# evolution_journal 记录正常进化
async def record_evolution(self, entry: EvolutionEntry) -> None:
    ...

# 单独记录回滚
async def record_rollback(
    self,
    previous_version: int,
    reason: str,
    snapshot_ref: str | None
) -> None:
    ...
```

---

## 9. 漂移检测多因素化

### 9.1 之前：仅规则数量

Phase 16 的漂移检测仅基于规则数量：

```python
# 旧逻辑
def _detect_drift(self) -> bool:
    rule_count_delta = len(new_rules) - len(old_rules)
    return rule_count_delta > DRIFT_THRESHOLD
```

### 9.2 现在：多因素检测

Phase 17 的漂移检测升级为多因素：

```python
@dataclass
class DriftFactors:
    behavior_rule_delta: float    # 行为规则变化量
    traits_delta: float          # 特质变化量
    relationship_style_delta: float  # 关系风格变化量
    baseline_empty: bool         # baseline 描述是否为空


DRIFT_THRESHOLDS = {
    "behavior_rule": 0.3,        # 规则变化超过 30%
    "traits": 0.25,              # 特质变化超过 25%
    "relationship_style": 0.2,   # 关系风格变化超过 20%
    "baseline_empty": True,       # baseline 为空即触发
}


def _detect_drift(self, old: PersonalityState, new: PersonalityState) -> bool:
    factors = DriftFactors(
        behavior_rule_delta=self._calc_rule_delta(old, new),
        traits_delta=self._calc_traits_delta(old, new),
        relationship_style_delta=self._calc_style_delta(old, new),
        baseline_empty=not new.core_personality.baseline_description.strip(),
    )
    
    # 任一因素超标即触发漂移
    return (
        factors.behavior_rule_delta > DRIFT_THRESHOLDS["behavior_rule"]
        or factors.traits_delta > DRIFT_THRESHOLDS["traits"]
        or factors.relationship_style_delta > DRIFT_THRESHOLDS["relationship_style"]
        or factors.baseline_empty
    )
```

### 9.3 各因素计算方式

```python
def _calc_rule_delta(self, old: PersonalityState, new: PersonalityState) -> float:
    old_rules = set(r.rule for r in old.core_personality.behavioral_rules)
    new_rules = set(r.rule for r in new.core_personality.behavioral_rules)
    
    added = len(new_rules - old_rules)
    removed = len(old_rules - new_rules)
    total = max(len(old_rules), len(new_rules), 1)
    
    return (added + removed) / total


def _calc_traits_delta(self, old: PersonalityState, new: PersonalityState) -> float:
    old_traits = old.core_personality.traits_internal
    new_traits = new.core_personality.traits_internal
    
    all_keys = set(old_traits.keys()) | set(new_traits.keys())
    if not all_keys:
        return 0.0
    
    delta_sum = sum(
        abs(old_traits.get(k, 0.0) - new_traits.get(k, 0.0))
        for k in all_keys
    )
    
    return delta_sum / len(all_keys)


def _calc_style_delta(self, old: PersonalityState, new: PersonalityState) -> float:
    fields = ["warmth", "boundary_strength", "supportiveness", "humor", "preferred_closeness"]
    
    deltas = []
    for field in fields:
        old_val = getattr(old.relationship_style, field, 0.5)
        new_val = getattr(new.relationship_style, field, 0.5)
        deltas.append(abs(old_val - new_val))
    
    return sum(deltas) / len(deltas) if deltas else 0.0
```

---

## 10. SoulEngine Prompt 更新

### 10.1 之前：混合人格

Phase 16 的 SoulEngine prompt 混合了人格内容：

```
## Baseline Personality
{baseline_description}

## Behavioral Rules
{behavioral_rules}

## Session Adaptations
{session_adaptations}
```

### 10.2 现在：分层人格

Phase 17 的 SoulEngine prompt 分离了三层人格：

```
## Stable Identity (Long-term)
{core_personality.baseline_description}

## Behavioral Rules (Persistent)
{core_personality.behavioral_rules}

## Relationship Style (Long-term)
{relationship_style_formatted}

## Session Adaptation (Temporary - Current Session Only)
{session_adaptations}
```

### 10.3 Prompt 格式化

```python
def _format_relationship_style(self, style: RelationshipStyle) -> str:
    """格式化关系风格为自然语言"""
    warmth_desc = {
        0.0: "非常冷淡", 0.3: "较为冷淡", 0.5: "中性", 0.7: "温暖", 1.0: "非常热情"
    }.get(style.warmth, "中性")
    
    boundary_desc = {
        0.0: "无边界", 0.3: "边界较弱", 0.5: "适度边界", 0.7: "边界较强", 1.0: "边界极强"
    }.get(style.boundary_strength, "适度边界")
    
    return f"""Warmth: {warmth_desc}
Boundary Strength: {boundary_desc}
Supportiveness: {style.supportiveness:.0%}
Humor: {style.humor:.0%}
Preferred Closeness: {style.preferred_closeness:.0%}"""


def _format_session_adaptation(self, adaptation: SessionAdaptation) -> str:
    """格式化会话适应，明确标记为短期"""
    items = "\n".join(f"- {item}" for item in adaptation.current_items)
    return f"""[TEMPORARY - Current Session Only]
Session: {adaptation.session_id}
Items:
{items}
[Do not treat these as permanent personality traits]"""
```

---

## 11. CoreMemoryStore 向后兼容

### 11.1 旧快照兼容

Phase 17 保留了对旧快照的向后兼容：

```python
async def load_latest(self, user_id: str) -> CoreMemory:
    """加载最新快照，自动迁移旧格式"""
    snapshot = await self._fetch_latest_snapshot(user_id)
    
    if snapshot.version < 2:
        # 旧版本格式，需要迁移
        return self._migrate_from_v1(snapshot)
    
    return snapshot


def _migrate_from_v1(self, old_snapshot: dict) -> CoreMemory:
    """将 v1 快照迁移到 v2 分层结构"""
    old_personality = old_snapshot.get("personality", {})
    
    # 映射旧字段到新结构
    return PersonalityState(
        core_personality=CorePersonality(
            baseline_description=old_personality.get("baseline_description", ""),
            behavioral_rules=old_personality.get("behavioral_rules", []),
            traits_internal=old_personality.get("traits_internal", {}),
            stable_fields={},
            updated_at=utc_now(),
        ),
        relationship_style=RelationshipStyle(
            warmth=0.5,
            boundary_strength=0.5,
            supportiveness=0.5,
            humor=0.5,
            preferred_closeness=0.5,
        ),
        session_adaptation=SessionAdaptation(
            current_items=old_personality.get("session_adaptations", []),
            session_id=None,
            created_at=utc_now(),
            expires_at=utc_now() + SESSION_ADAPTATION_TTL,
        ),
        version=2,
        snapshot_version=1,
    )
```

### 11.2 快照版本协调

Phase 17 确保 core-memory 快照使用 self-cognition version 和 personality version 的**最大值**：

```python
async def save_snapshot(self, core_memory: CoreMemory) -> None:
    # 使用两个 version 的最大值，确保任一更新都会创建新快照
    max_version = max(
        core_memory.self_cognition.version,
        core_memory.personality.version,
    )
    
    snapshot = CoreMemorySnapshot(
        user_id=core_memory.user_id,
        version=max_version,
        personality_version=core_memory.personality.version,
        self_cognition_version=core_memory.self_cognition.version,
        data=asdict(core_memory),
        created_at=utc_now(),
    )
    
    await self._save(snapshot)
```

---

## 12. 验证与验收

### 12.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 12.2 验收检查项

- [ ] 77 个测试全部通过（Phase 16 的 72 + Phase 17 新增）
- [ ] `test_personality_evolver.py` 存在且覆盖关键路径
- [ ] PersonalityState 三层结构正确定义
- [ ] CorePersonality / RelationshipStyle / SessionAdaptation 字段完整
- [ ] 版本化快照（SnapshotRecord）正确定义
- [ ] fast_adapt() 仅修改 SessionContextStore
- [ ] slow_evolve() 修改长期人格前先创建快照
- [ ] 规则晋升需重复信号跨多个会话
- [ ] 多因素漂移检测正确工作
- [ ] 回滚恢复长期人格，不影响 session_adaptation
- [ ] 回滚事件单独记录到 journal
- [ ] SoulEngine prompt 正确分离三层人格
- [ ] 会话适应明确标记为 "temporary and current-session-only"
- [ ] 旧快照向后兼容迁移正确

### 12.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_personality_evolver.py` | Phase 17 新增，测试快/慢适应、快照、回滚 |
| `tests/test_soul_engine.py` | 更新覆盖人格分层 prompt |
| `tests/conftest.py` | 更新人格相关 fixtures |

---

## 13. Explicitly Not Done Yet

以下功能在 Phase 17 中**仍未完成**：

- [ ] 持久化快照后端（当前仅为内存存储）
- [ ] 长期人格变化的候选审查管道（重复信号仍直接流入 slow_evolve()）
- [ ] 超越当前最小数值/style 字段的关系风格 taxonomy
- [ ] 测试/journey 事件之外的的人格版本/回滚历史专用可观测面
- [ ] 会话适应的显式过期 sweeper（仅依赖有界存储和 prompt-time 处理）

---

## 14. Phase 17 的意义

### 14.1 从"能进化"到"稳定进化"

Phase 17 完成后，系统从"能进化"升级到"稳定进化"：

```
Phase 16 之前
     ↓
人格进化可能：
     ↓
短期信号 → 直接修改人格 → 人格不稳定

Phase 17 新增
     ↓
快适应（短期信号）↔ 慢进化（长期人格）分离
     ↓
版本化快照 + 回滚机制
     ↓
多因素漂移检测
     ↓
人格演变可追溯、可回滚
```

### 14.2 为未来 Phase 奠定基础

Phase 17 建立的人格稳定性机制是后续 Phase 的基石：

- Phase 18 候选审查管道 → 基于当前的版本化快照结构
- 更丰富的关系风格 taxonomy → 基于当前的最小结构扩展
- 专用可观测面 → 基于当前的 journal 事件

### 14.3 关键设计原则

Phase 17 确立的关键设计原则：

| 原则 | 说明 |
|------|------|
| **快慢分离** | fast_adapt() 不修改长期人格 |
| **版本化** | 所有快照版本化，支持回滚 |
| **多因素检测** | 漂移检测考虑规则、特质、关系风格 |
| **日志分离** | 回滚事件与正常进化事件分开记录 |
| **向后兼容** | 旧快照自动迁移到新结构 |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-16-学习笔记]] — 关系记忆基础
- [[../phase_17_status.md|phase_17_status.md]] — Phase 17 给 Codex 的状态文档
