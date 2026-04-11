# Phase 16 学习笔记：关系记忆基础

> **前置阶段**：[[Phase-15-学习笔记]]  
> **目标**：建立显式持久化记忆schema，区分事实、推断和关系记忆，支持用户确认机制  
> **里程碑**：本阶段完成后系统具备truth-aware记忆能力，前台推理可区分记忆的置信度和状态

---

## 目录

- [概述](#概述)
- [1. Phase 16 文件清单](#1-phase-16-文件清单)
- [2. 为什么需要关系记忆](#2-为什么需要关系记忆)
- [3. 新的记忆类型体系](#3-新的记忆类型体系)
- [4. 持久化元数据设计](#4-持久化元数据设计)
- [5. WorldModel 结构化升级](#5-worldmodel-结构化升级)
- [6. GraphStore 关系历史保留](#6-graphstore-关系历史保留)
- [7. VectorRetriever truth元数据传递](#7-vectorretriever-truth元数据传递)
- [8. CognitionUpdater 分类路由](#8-cognitionupdater-分类路由)
- [9. 记忆确认 HITL 工作流](#9-记忆确认-hitl-工作流)
- [10. CoreMemoryScheduler 保留策略](#10-corememoryscheduler-保留策略)
- [11. SoulEngine truth标记](#11-soulinge-truth标记)
- [12. 验证与验收](#12-验证与验收)
- [13. Explicitly Not Done Yet](#13-explicitly-not-done-yet)
- [14. Phase 16 的意义](#14-phase-16-的意义)

---

## 概述

### 目标

Phase 16 的目标是**建立关系记忆基础**，让系统具备：

- 显式持久化记忆schema（区分事实/推断/关系）
- truth-aware元数据（置信度、来源、时间范围、敏感性）
- 用户确认机制（低置信度/敏感记忆需用户确认）
- 冲突表示（不静默覆盖已确认记忆）

### Phase 15 到 Phase 16 的演进

Phase 15 完成了集成测试，系统"能验证"了。Phase 16 则让记忆系统"更可信"：

```
Phase 15 之前
     ↓
记忆以通用bucket形式存储
     ↓
WorldModel 包含 generic buckets（环境约束、社交规则等）
     ↓
检索返回的内容对前台模型"一视同仁"
     ↓
推断和事实被平等对待，可能导致推理偏差

Phase 16 新增
     ↓
显式记忆类型：FactualMemory / InferredMemory / RelationshipMemory
     ↓
truth元数据：confidence / source / confirmed_by_user / truth_type
     ↓
WorldModel 结构化：confirmed facts / inferred memory / relationship history
     ↓
检索结果携带truth/status标记，前台模型可区分记忆状态
```

### 新的系统形态

```
记忆写入流程
     ↓
Observer / SignalExtractor 抽取知识
     ↓
CognitionUpdater 分类路由
     ↓
┌─────────────────────────────────────────┐
│  truth_type 分类                        │
├─────────────────────────────────────────┤
│  FACT      → 直接写入 confirmed         │
│  INFERENCE → 写入 pending 或 confirmed  │
│  RELATION  → 写入关系图谱               │
│  SENSITIVE → 写入 pending_confirmation  │
└─────────────────────────────────────────┘
     ↓
低置信度/敏感记忆 → HITL 用户确认
     ↓
用户确认 → 晋升为 active memory
用户拒绝 → 保留冲突/替代轨迹
```

---

## 1. Phase 16 文件清单

| 文件 | 内容 |
|------|------|
| `app/memory/core_memory.py` | 新增 FactualMemory / InferredMemory / RelationshipMemory / DurableMemory |
| `app/memory/graph_store.py` | 扩展关系持久化，保留历史记录 |
| `app/memory/vector_retriever.py` | 扩展payload携带truth/status元数据 |
| `app/evolution/cognition_updater.py` | 分类路由、pending确认、冲突表示 |
| `app/evolution/core_memory_scheduler.py` | 保留 confirmed / pending / conflicts |
| `app/soul/engine.py` | truth标记prompt格式化 |
| `app/evolution/personality_evolver.py` | 修复损坏的实现 |
| `tests/test_relationship_memory.py` | Phase 16 新增测试 |
| `tests/test_soul_engine.py` | 更新以覆盖truth元数据 |

---

## 2. 为什么需要关系记忆

### 2.1 之前的问题

Phase 15 之前，记忆系统存在以下问题：

| 问题 | 描述 |
|------|------|
| **无区分** | 事实和推断被平等对待，前台模型无法区分置信度 |
| **静默覆盖** | GraphStore直接覆盖已有关系，历史关系丢失 |
| **无确认机制** | 低置信度推断没有用户确认流程，直接进入长期记忆 |
| **元数据缺失** | 记忆没有来源、置信度、时间范围等元数据 |
| **冲突未表示** | 新记忆与旧记忆冲突时，没有冲突表示机制 |

### 2.2 关系记忆的价值

```
关系记忆 = 显式结构 + truth元数据 + 用户确认 + 冲突表示

价值1: 推理更准确
    ↓
前台模型知道哪些是confirmed facts，哪些是pending inference
    ↓
推理时对不同truth级别的记忆加权不同

价值2: 用户信任
    ↓
敏感记忆/低置信度记忆需要用户确认
    ↓
用户对AI的知识有控制和可见性

价值3: 知识积累可追溯
    ↓
关系历史保留
    ↓
可以追踪用户偏好/习惯的演变
```

---

## 3. 新的记忆类型体系

### 3.1 三种记忆类型

Phase 16 引入了三种显式持久化记忆类型：

```python
@dataclass
class FactualMemory:
    """可验证的事实记忆，有明确来源，置信度高"""
    content: str                          # 记忆内容
    source: str                           # 来源：user_statement / observed_behavior / external_knowledge
    confidence: float                      # 置信度 0.0-1.0
    updated_at: datetime                   # 更新时间
    confirmed_by_user: bool = False       # 是否用户确认
    time_horizon: str = "permanent"       # 时间范围：permanent / long_term / recent
    sensitivity: str = "normal"            # 敏感性：normal / sensitive / restricted


@dataclass
class InferredMemory:
    """推断记忆，基于观察推断，置信度可变"""
    content: str                          # 推断内容
    inference_chain: list[str]            # 推断链/依据
    confidence: float                      # 置信度 0.0-1.0
    updated_at: datetime                   # 更新时间
    confirmed_by_user: bool = False       # 是否用户确认
    truth_type: str = "inference"          # 记忆类型
    time_horizon: str = "long_term"       # 时间范围
    sensitivity: str = "normal"            # 敏感性
    status: str = "active"                # 状态：active / pending_confirmation / superseded / conflict


@dataclass
class RelationshipMemory:
    """关系记忆，关于用户偏好、习惯、关系模式的记忆"""
    subject: str                          # 主体（用户/AI/第三方）
    predicate: str                        # 关系类型：PREFERS / DISLIKES / USES / ...
    object: str                           # 对象
    evidence: list[str]                   # 证据列表
    confidence: float                      # 置信度
    updated_at: datetime                   # 更新时间
    confirmed_by_user: bool = False       # 是否用户确认
    history: list[dict] = field(default_factory=list)  # 关系历史
    status: str = "active"                # 状态
```

### 3.2 统一元数据契约

三种记忆类型共享 `DurableMemory` 元数据契约：

```python
@dataclass
class DurableMemory:
    """所有持久化记忆共享的元数据"""
    source: str                           # 来源
    confidence: float                      # 置信度
    updated_at: datetime                   # 更新时间
    confirmed_by_user: bool = False       # 用户确认
    truth_type: str                       # truth类型：fact / inference / relation
    time_horizon: str                     # 时间范围
    status: str = "active"               # 状态：active / pending_confirmation / superseded / conflict
    sensitivity: str = "normal"           # 敏感性
```

---

## 4. 持久化元数据设计

### 4.1 元数据字段

Phase 16 为所有记忆添加了以下持久化元数据：

| 字段 | 类型 | 说明 |
|------|------|------|
| `source` | str | 来源：user_statement / observed_behavior / inferred / external |
| `confidence` | float | 置信度 0.0-1.0 |
| `updated_at` | datetime | 更新时间戳 |
| `confirmed_by_user` | bool | 是否用户确认 |
| `truth_type` | str | fact / inference / relation |
| `time_horizon` | str | permanent / long_term / recent |
| `status` | str | active / pending_confirmation / superseded / conflict |
| `sensitivity` | str | normal / sensitive / restricted |

### 4.2 置信度阈值规则

```python
CONFIDENCE_THRESHOLDS = {
    "auto_confirm": 0.8,      # 置信度 > 0.8，自动确认
    "user_confirm": 0.5,      # 0.5 < 置信度 <= 0.8，需用户确认
    "discard": 0.0,          # 置信度 < 0.5，丢弃
}

SENSITIVITY_RULES = {
    "sensitive": ["preference", "habit", "personal"],  # 敏感内容
    "restricted": ["health", "financial", "legal"],    # 限制内容
}
```

### 4.3 时间范围分类

| 时间范围 | 说明 |
|---------|------|
| `permanent` | 永久事实，如用户姓名、出生日期 |
| `long_term` | 长期知识，如偏好、习惯 |
| `recent` | 近期观察，可能随时间变化 |

---

## 5. WorldModel 结构化升级

### 5.1 之前：通用Bucket

Phase 15 的 WorldModel 使用通用bucket：

```python
class WorldModel:
    env_constraints: list[MemoryEntry]      # 环境约束
    social_rules: list[MemoryEntry]           # 社交规则
    user_model: dict[str, MemoryEntry]       # 用户模型
    agent_profiles: dict[str, MemoryEntry]   # Agent画像
```

问题：前台模型无法区分 fact 和 inference。

### 5.2 现在：结构化Section

Phase 16 的 WorldModel 结构化升级：

```python
class WorldModel:
    # 确认的事实（高置信度，用户确认或高置信度自动确认）
    confirmed_facts: list[FactualMemory]
    
    # 推断记忆（中等置信度，需用户确认）
    inferred_memory: list[InferredMemory]
    
    # 关系历史（来自图谱）
    relationship_history: list[RelationshipMemory]
    
    # 待确认记忆（低置信度或敏感，需用户确认）
    pending_confirmations: list[DurableMemory]
    
    # 记忆冲突（冲突的记忆并列显示）
    memory_conflicts: list[dict]
```

### 5.3 向后兼容

Phase 16 保留了对旧快照的向后兼容：

```python
def _migrate_legacy_entry(self, entry: MemoryEntry) -> FactualMemory:
    """将旧的MemoryEntry映射为新的FactualMemory"""
    return FactualMemory(
        content=entry.content,
        source="legacy_snapshot",
        confidence=0.7,  # 旧记忆默认中等置信度
        updated_at=entry.created_at,
        confirmed_by_user=False,
        time_horizon="long_term",
        sensitivity="normal",
    )
```

---

## 6. GraphStore 关系历史保留

### 6.1 之前：静默覆盖

Phase 15 之前，GraphStore 写入关系时直接覆盖：

```python
# 旧逻辑
async def upsert_relation(self, relation: Relation) -> None:
    # 直接覆盖已有关系，历史丢失
    await self.write_relation(relation)
```

### 6.2 现在：保留历史

Phase 16 的 GraphStore 保留关系历史：

```python
async def upsert_relation(self, relation: Relation) -> None:
    # 1. 查询现有关系
    existing = await self.get_relation(relation.subject, relation.predicate)
    
    if existing:
        # 2. 将现有关系移入历史
        await self._archive_relation(existing)
        
        # 3. 写入新关系（带历史引用）
        relation.history = existing.history + [asdict(existing)]
    
    # 4. 写入新关系
    await self.write_relation(relation)


async def _archive_relation(self, relation: Relation) -> None:
    """将关系归档为历史"""
    relation.status = "superseded"
    await self.write_history_entry(
        subject=relation.subject,
        predicate=relation.predicate,
        object=relation.object,
        archived_at=utc_now(),
        reason="superseded_by_new_evidence",
    )
```

### 6.3 关系状态

| 状态 | 说明 |
|------|------|
| `active` | 当前活跃关系 |
| `superseded` | 被新关系替代 |
| `conflict` | 与活跃关系冲突 |

---

## 7. VectorRetriever truth元数据传递

### 7.1 之前：纯内容返回

Phase 15 的 VectorRetriever 返回纯内容：

```python
async def retrieve(self, query: str, limit: int = 8) -> dict:
    results = await self.qdrant.search(query, limit=limit)
    return {
        "matches": [
            {"content": r.payload["content"]}  # 只有内容
            for r in results
        ]
    }
```

### 7.2 现在：携带truth元数据

Phase 16 的 VectorRetriever 携带完整truth元数据：

```python
async def retrieve(self, query: str, limit: int = 8) -> dict:
    results = await self.qdrant.search(query, limit=limit)
    return {
        "matches": [
            {
                "content": r.payload["content"],
                "truth_type": r.payload.get("truth_type", "unknown"),
                "confidence": r.payload.get("confidence", 0.5),
                "status": r.payload.get("status", "active"),
                "source": r.payload.get("source", "unknown"),
                "updated_at": r.payload.get("updated_at"),
                "sensitivity": r.payload.get("sensitivity", "normal"),
            }
            for r in results
        ]
    }
```

### 7.3 前台模型可见性

检索结果现在对前台模型可见truth标记：

```
## Retrieved Context
- [fact] 用户偏好使用Python进行数据分析 | confidence=0.9 | status=confirmed
- [inference] 用户可能对机器学习感兴趣 | confidence=0.6 | status=pending_confirmation
- [relation] 用户 USES Python | confidence=0.85 | status=active
```

---

## 8. CognitionUpdater 分类路由

### 8.1 Lesson分类

Phase 16 的 CognitionUpdater 将 Lesson 分类路由：

```python
async def handle_lesson_generated(self, event: Event) -> None:
    lesson = event.payload["lesson"]
    
    # 分类路由
    if lesson.is_fact:
        await self._handle_fact_lesson(lesson)
    elif lesson.is_inference:
        await self._handle_inference_lesson(lesson)
    elif lesson.is_relation:
        await self._handle_relation_lesson(lesson)
    else:
        await self._handle_generic_lesson(lesson)


async def _handle_fact_lesson(self, lesson: Lesson) -> None:
    """高置信度事实 → 直接确认写入"""
    if lesson.confidence >= CONFIDENCE_THRESHOLDS["auto_confirm"]:
        memory = FactualMemory(
            content=lesson.content,
            source="observed_behavior",
            confidence=lesson.confidence,
            updated_at=utc_now(),
            confirmed_by_user=True,  # 自动确认
        )
        await self.core_memory_scheduler.write_factual(memory)


async def _handle_inference_lesson(self, lesson: Lesson) -> None:
    """推断记忆 → 按置信度路由"""
    if lesson.confidence >= CONFIDENCE_THRESHOLDS["auto_confirm"]:
        await self._write_active_inference(lesson)
    elif lesson.confidence >= CONFIDENCE_THRESHOLDS["user_confirm"]:
        await self._create_confirmation_task(lesson)
    else:
        await self._discard_lesson(lesson)


async def _handle_relation_lesson(self, lesson: Lesson) -> None:
    """关系记忆 → 写入图谱"""
    await self.graph_store.upsert_relation(
        subject=lesson.subject,
        predicate=lesson.predicate,
        object=lesson.object,
        evidence=[lesson.content],
        confidence=lesson.confidence,
    )
```

### 8.2 冲突表示

Phase 16 不再静默覆盖冲突记忆：

```python
async def _check_conflict(self, new_memory: DurableMemory) -> list[DurableMemory]:
    """检查新记忆与现有记忆是否冲突"""
    existing = await self.core_memory_store.get_active(new_memory.key)
    
    if existing and existing.truth_type == new_memory.truth_type:
        # 同类型记忆，置信度相近 → 冲突
        if abs(existing.confidence - new_memory.confidence) < 0.2:
            return [existing, new_memory]
    
    return []


async def _handle_inference_lesson(self, lesson: Lesson) -> None:
    conflicts = await self._check_conflict(new_memory)
    
    if conflicts:
        # 有冲突 → 创建冲突表示，不覆盖
        await self.core_memory_scheduler.write_conflict(
            existing=conflicts[0],
            new=new_memory,
        )
    else:
        # 无冲突 → 正常写入
        await self._write_active_inference(lesson)
```

---

## 9. 记忆确认 HITL 工作流

### 9.1 确认任务创建

低置信度或敏感记忆触发确认任务：

```python
async def _create_confirmation_task(self, lesson: Lesson) -> None:
    """创建记忆确认HITL任务"""
    task = await self.task_system.create(
        intent=f"memory_confirmation: {lesson.content[:100]}",
        prompt_snapshot=f"请确认以下记忆是否正确：\n\n{lesson.content}",
        metadata={
            "memory_confirmation": {
                "lesson": asdict(lesson),
                "truth_type": lesson.truth_type,
                "confidence": lesson.confidence,
            }
        },
    )
    
    # 任务状态设为 waiting_hitl
    await self.task_system.set_waiting_hitl(task.id)
```

### 9.2 HITL 决策处理

HITL 响应支持三种决策：

| 决策 | 行为 |
|------|------|
| `approve` | 将pending memory晋升为active memory |
| `reject` | 保留冲突/替代轨迹，标记为rejected |
| `defer` | 保持pending状态，稍后确认 |

```python
async def handle_hitl_feedback(self, task_id: str, decision: str) -> None:
    task = await self.task_store.get(task_id)
    memory_data = task.metadata.get("memory_confirmation", {})
    
    if decision == "approve":
        # 晋升为active memory
        await self._promote_memory(memory_data)
    elif decision == "reject":
        # 保留冲突轨迹
        await self._mark_superseded(memory_data)
    elif decision == "defer":
        # 保持pending
        pass
```

### 9.3 工作流图

```
CognitionUpdater 产出 Lesson
     ↓
┌─────────────────────────────────────────┐
│  置信度判断                              │
├─────────────────────────────────────────┤
│  confidence >= 0.8  → 直接确认写入       │
│  0.5 <= confidence < 0.8 → 创建确认任务  │
│  confidence < 0.5   → 丢弃               │
└─────────────────────────────────────────┘
     ↓
Task.status = "waiting_hitl"
     ↓
用户收到 HITL 弹窗
     ↓
┌─────────────────────────────────────────┐
│  用户决策                               │
├─────────────────────────────────────────┤
│  approve  → 晋升为 active memory         │
│  reject   → 保留冲突轨迹                 │
│  defer    → 保持 pending                 │
└─────────────────────────────────────────┘
```

---

## 10. CoreMemoryScheduler 保留策略

### 10.1 保留的记忆类型

CoreMemoryScheduler 在压缩/重建时保留以下内容：

| 类型 | 保留策略 |
|------|---------|
| confirmed memories | 优先保留，不压缩 |
| pending confirmations | 保留，供用户确认 |
| conflict summaries | 保留，显示冲突历史 |
| relationship history | 从图谱重建 |

```python
async def rebuild_world_model(self, user_id: str) -> WorldModel:
    # 1. 获取confirmed facts
    confirmed = await self.core_memory_store.get_by_status(
        user_id, status="confirmed"
    )
    
    # 2. 获取pending confirmations
    pending = await self.core_memory_store.get_by_status(
        user_id, status="pending_confirmation"
    )
    
    # 3. 获取冲突摘要
    conflicts = await self.core_memory_store.get_conflicts(user_id)
    
    # 4. 从图谱重建关系历史
    relationships = await self.graph_store.get_relation_history(user_id)
    
    return WorldModel(
        confirmed_facts=confirmed,
        inferred_memory=pending,
        pending_confirmations=pending,
        memory_conflicts=conflicts,
        relationship_history=relationships,
    )
```

### 10.2 压缩时的保护规则

```python
COMPRESSION_PROTECTION_RULES = {
    "confirmed_facts": "never_compress",     # 确认事实永不压缩
    "relationship_history": "never_compress", # 关系历史永不压缩
    "pending_confirmations": "never_compress", # 待确认记忆永不压缩
    "inferred_memory": "compress_if_needed",  # 推断记忆可压缩
}
```

---

## 11. SoulEngine truth标记

### 11.1 之前：纯文本

Phase 15 的检索上下文格式化：

```
## Retrieved Context
- 用户偏好Python进行数据分析
- 用户可能对机器学习感兴趣
- 用户使用Python进行编程
```

问题：前台模型无法区分 fact 和 inference。

### 11.2 现在：truth标记

Phase 16 的检索上下文格式化：

```
## Retrieved Context
- [FACT | confirmed] 用户偏好使用Python进行数据分析 | confidence=0.9
- [INFERENCE | pending] 用户可能对机器学习感兴趣 | confidence=0.6
- [RELATION | active] 用户 USES Python | confidence=0.85
- [FACT | pending | SENSITIVE] 用户的职业是律师 | confidence=0.5 | ⚠️待确认
```

### 11.3 Prompt格式化

```python
def _format_retrieved_context(self, matches: list[dict]) -> str:
    lines = []
    for item in matches:
        truth_type = item.get("truth_type", "unknown").upper()
        status = item.get("status", "active")
        confidence = item.get("confidence", 0.0)
        sensitivity = item.get("sensitivity", "normal")
        
        # 状态标记
        status_marker = {
            "confirmed": "✓",
            "active": "",
            "pending_confirmation": "⏳待确认",
            "superseded": "✗已替代",
            "conflict": "⚠️冲突",
        }.get(status, "")
        
        # 敏感性标记
        sensitive_marker = "⚠️敏感" if sensitivity == "sensitive" else ""
        
        line = f"- [{truth_type} | {status}] {item['content']} | conf={confidence:.2f} {status_marker} {sensitive_marker}"
        lines.append(line)
    
    return "\n".join(lines) if lines else "- No retrieved context."
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

- [ ] 72 个测试全部通过（Phase 15 的 66 + Phase 16 新增）
- [ ] `test_relationship_memory.py` 存在且覆盖关键路径
- [ ] FactualMemory / InferredMemory / RelationshipMemory 类型正确
- [ ] truth元数据（source / confidence / confirmed_by_user / truth_type / time_horizon / status / sensitivity）正确传递
- [ ] WorldModel 结构化section正确渲染
- [ ] GraphStore 保留关系历史
- [ ] VectorRetriever 携带truth元数据
- [ ] CognitionUpdater 分类路由正确
- [ ] 记忆确认HITL工作流端到端正确
- [ ] CoreMemoryScheduler 保留策略正确
- [ ] SoulEngine truth标记正确显示

### 12.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_relationship_memory.py` | Phase 16 新增，测试记忆类型、元数据、确认工作流 |
| `tests/test_soul_engine.py` | 更新以覆盖truth元数据prompt格式化 |

---

## 13. Explicitly Not Done Yet

以下功能在 Phase 16 中**仍未完成**：

- [ ] 专用用户-facing记忆管理UI
- [ ] 记忆特定列表/查询API（仅内部运行时使用）
- [ ] 后台创建的确认请求的自动客户端投递路径
- [ ] 历史图谱边标准化迁移（已有数据不带新元数据）
- [ ] 敏感记忆taxonomy的丰富策略层（当前仅 simple `details["sensitive"]` / confidence规则）

---

## 14. Phase 16 的意义

### 14.1 从"能记忆"到"可信记忆"

Phase 16 完成后，系统从"能记忆"升级到"可信记忆"：

```
Phase 15 之前
     ↓
记忆存储 → 前台使用
     ↓
事实和推断无区分
     ↓
可能产生推理偏差

Phase 16 新增
     ↓
记忆分类（fact / inference / relation）
     ↓
truth元数据（置信度、来源、状态）
     ↓
用户确认机制
     ↓
冲突表示
     ↓
前台模型可区分记忆可信度
```

### 14.2 为未来Phase奠定基础

Phase 16 建立的关系记忆基础是后续Phase的基石：

- 记忆确认UX → 基于当前的 `memory_confirmation` HITL元数据契约
- 更丰富的记忆抽取 → 更新现有测试后扩展
- 敏感记忆策略 → 基于当前的simple规则扩展

### 14.3 技术债务清理

Phase 16 同时修复了 `app/evolution/personality_evolver.py` 中的损坏实现：

- 该文件之前无法正常编译
- 修复后不影响现有功能
- 为后续Phase扫清障碍

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-15-学习笔记]] — 集成与端到端置信度
- [[../phase_16_status.md|phase_16_status.md]] — Phase 16 给 Codex 的状态文档
