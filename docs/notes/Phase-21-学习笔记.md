# Phase 21 学习笔记：用户记忆治理

> **前置阶段**：[[Phase-20-学习笔记]]  
> **目标**：建立用户记忆治理机制，支持记忆查看、修正、删除、阻止学习，以及治理策略配置  
> **里程碑**：本阶段完成后系统具备用户-facing记忆治理能力，记忆修正/删除通过审计替换而非覆盖

---

## 目录

- [概述](#概述)
- [1. Phase 21 文件清单](#1-phase-21-文件清单)
- [2. 为什么需要用户记忆治理](#2-为什么需要用户记忆治理)
- [3. MemoryGovernancePolicy 数据结构](#3-memorygovernancepolicy-数据结构)
- [4. 默认保留策略](#4-默认保留策略)
- [5. MemoryGovernanceService 设计](#5-memorygovernanceservice-设计)
- [6. 修正语义](#6-修正语义)
- [7. 删除语义](#7-删除语义)
- [8. 阻止学习语义](#8-阻止学习语义)
- [9. 用户-facing API](#9-用户-facing-api)
- [10. CognitionUpdater 集成](#10-cognitionupdater-集成)
- [11. CoreMemoryScheduler 集成](#11-corememoryscheduler-集成)
- [12. GraphStore 关系失效支持](#12-graphstore-关系失效支持)
- [13. 运行时连接](#13-运行时连接)
- [14. 验证与验收](#14-验证与验收)
- [15. Explicitly Not Done Yet](#15-explicitly-not-done-yet)
- [16. Phase 21 的意义](#16-phase-21-的意义)

---

## 概述

### 目标

Phase 21 的目标是**建立用户记忆治理机制**，让系统具备：

- 用户可见的世界模型记忆列表
- 记忆修正（通过审计替换，非覆盖）
- 记忆删除（治理元数据 + 候选回滚）
- 阻止未来学习（指定内容类别）
- 治理策略配置（保留天数、阻塞类别）

### Phase 20 到 Phase 21 的演进

Phase 20 建立了关系状态机，系统能感知关系阶段。Phase 21 则关注**用户对记忆的控制权**：

```
Phase 20 完成时
     ↓
关系阶段状态机 + 记忆系统
     ↓
系统具备完整的记忆积累能力
     ↓
但用户无法控制记忆
     ↓
     ↓
┌─────────────────────────────────────────┐
│  Phase 20 的治理缺失                      │
├─────────────────────────────────────────┤
│  • 用户无法查看记忆                       │
│  • 无法修正错误记忆                       │
│  • 无法删除不需要的记忆                   │
│  • 无法阻止某类别的学习                   │
│  • 记忆修正直接覆盖，无审计               │
└─────────────────────────────────────────┘

Phase 21 新增
     ↓
用户记忆治理 API
     ↓
GET /memory - 查看记忆
POST /memory/correct - 修正记忆
POST /memory/delete - 删除记忆
POST /memory/governance/block - 阻止学习
GET /memory/governance - 治理策略
     ↓
修正/删除通过审计替换
     ↓
治理事件记录到 journal
```

### 治理范围边界

Phase 21 的治理**明确限定**于世界模型记忆：

| 可治理 | 不可治理 |
|--------|---------|
| `confirmed_facts` | `self_cognition` |
| `inferred_memories` | `personality` |
| `relationship_history` | `relationship_style` |
| `pending_confirmations` | |
| `memory_conflicts` | |

---

## 1. Phase 21 文件清单

| 文件 | 内容 |
|------|------|
| `app/memory/core_memory.py` | 新增 MemoryGovernancePolicy |
| `app/memory/core_memory_store.py` | 更新快照序列化，兼容旧格式 |
| `app/memory/governance.py` | Phase 21 新增，MemoryGovernanceService |
| `app/evolution/cognition_updater.py` | 更新：阻止类别检查 |
| `app/evolution/core_memory_scheduler.py` | 更新：修剪治理记忆 |
| `app/memory/graph_store.py` | 更新：关系失效支持 |
| `app/evolution/candidate_pipeline.py` | 扩展：只读候选列表 |
| `app/api/memory.py` | Phase 21 新增，用户-facing治理 API |
| `app/api/models.py` | 更新：治理相关请求/响应模型 |
| `app/api/__init__.py` | 注册新路由 |
| `app/main.py` | 注册新路由 |
| `app/runtime/bootstrap.py` | 更新：注入治理服务 |
| `tests/test_memory_governance.py` | Phase 21 新增测试 |

---

## 2. 为什么需要用户记忆治理

### 2.1 之前的问题

Phase 20 之前，系统缺乏用户记忆治理：

| 问题 | 描述 | 影响 |
|------|------|------|
| **无法查看** | 用户无法看到系统记住了什么 | 透明度缺失 |
| **无法修正** | 错误记忆只能被覆盖，无法修正 | 记忆质量差 |
| **无法删除** | 不想要的记忆无法删除 | 隐私侵犯 |
| **无法阻止** | 无法阻止某类内容学习 | 用户控制缺失 |
| **覆盖而非替换** | 修正时直接覆盖，无审计 | 不可追溯 |

### 2.2 记忆治理的价值

```
记忆治理 = 透明度 + 控制权 + 审计

价值1: 透明度
    ↓
用户可见系统记忆了什么
     ↓
增强信任

价值2: 控制权
    ↓
修正/删除/阻止学习
     ↓
用户主导记忆

价值3: 审计
    ↓
所有变更记录到 journal
     ↓
可追溯、可回滚
```

---

## 3. MemoryGovernancePolicy 数据结构

### 3.1 定义

```python
@dataclass
class MemoryGovernancePolicy:
    """记忆治理策略"""
    
    blocked_content_classes: set[ContentClass]  # 阻塞的内容类别
    retention_days: dict[ContentClass, int]       # 各类别保留天数
    updated_at: datetime                        # 策略更新时间
```

### 3.2 内容类别

```python
class ContentClass:
    FACT = "fact"                      # 事实
    INFERENCE = "inference"            # 推断
    RELATIONSHIP = "relationship"      # 关系
    SUPPORT_PREFERENCE = "support_preference"  # 支持偏好
```

### 3.3 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `blocked_content_classes` | set[ContentClass] | 阻塞的内容类别，阻止未来学习 |
| `retention_days` | dict[ContentClass, int] | 各内容类别的保留天数（天），-1表示永久 |
| `updated_at` | datetime | 策略最后更新时间 |

---

## 4. 默认保留策略

### 4.1 各类别默认保留

```python
DEFAULT_RETENTION_POLICY = {
    ContentClass.FACT: 365,           # 事实：1年
    ContentClass.INFERENCE: 90,        # 推断：90天
    ContentClass.RELATIONSHIP: 180,    # 关系：6个月
    ContentClass.SUPPORT_PREFERENCE: 180,  # 支持偏好：6个月
}

RETENTION_FOREVER = -1  # 永久保留标记
```

### 4.2 特殊记忆类型保留

```python
SPECIAL_RETENTION = {
    "pending_confirmations": 30,   # 待确认：30天
    "memory_conflicts": 60,        # 冲突：60天
    "world_model_candidates": 14,  # 候选：14天
}
```

### 4.3 保留策略行为

| 类别 | 默认保留天数 | 行为 |
|------|-------------|------|
| `fact` | 365 | 过期后读取时过滤 |
| `inference` | 90 | 过期后修剪 |
| `relationship` | 180 | 过期后软删除 |
| `support_preference` | 180 | 过期后软删除 |
| `pending_confirmations` | 30 | 过期后修剪 |
| `memory_conflicts` | 60 | 过期后修剪 |
| `world_model_candidates` | 14 | 过期后修剪 |

---

## 5. MemoryGovernanceService 设计

### 5.1 服务职责

```python
class MemoryGovernanceService:
    """
    记忆治理服务
    - 列表用户可见的世界模型记忆
    - 区分 durable vs candidate 可见性
    - 通过审计替换修正记忆
    - 通过治理元数据 + 候选回滚删除记忆
    - 阻止指定内容类别的未来学习
    - 修剪过期的推断/待确认/冲突/候选条目
    - 写入治理事件到 evolution journal
    """
    
    def __init__(
        self,
        core_memory_store: CoreMemoryStore,
        graph_store: GraphStore | None,
        candidate_manager: EvolutionCandidateManager,
        evolution_journal: EvolutionJournal,
    ) -> None:
        ...
```

### 5.2 列表记忆

```python
async def list_memory(
    self,
    user_id: str,
    content_class: ContentClass | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> list[MemoryItem]:
    """
    列表用户可见的记忆
    - 默认不显示已删除内容
    - 支持按类别和状态过滤
    """
    
    items = []
    
    # 获取 durable memory
    if content_class in {None, ContentClass.FACT}:
        items.extend(await self._list_facts(user_id, include_deleted))
    
    if content_class in {None, ContentClass.INFERENCE}:
        items.extend(await self._list_inferences(user_id, include_deleted))
    
    if content_class in {None, ContentClass.RELATIONSHIP}:
        items.extend(await self._list_relationships(user_id, include_deleted))
    
    if content_class in {None, ContentClass.SUPPORT_PREFERENCE}:
        items.extend(await self._list_support_preferences(user_id, include_deleted))
    
    # 按状态过滤
    if status:
        items = [i for i in items if i.status == status]
    
    return items


@dataclass
class MemoryItem:
    """记忆条目"""
    id: str
    content_class: ContentClass
    content: str
    source: str
    confidence: float
    status: str                    # active / deleted / superseded / conflict
    visibility: str               # durable / candidate
    created_at: datetime
    updated_at: datetime
    metadata: dict
```

### 5.3 修正记忆

```python
async def correct_memory(
    self,
    user_id: str,
    memory_id: str,
    new_content: str,
    reason: str | None = None,
) -> MemoryCorrectionResult:
    """
    修正记忆
    - 原始条目被标记为 superseded
    - 新条目成为用户确认的事实
    - 新条目 source = "user_correction"
    """
    
    # 1. 获取原始记忆
    original = await self._get_memory_item(user_id, memory_id)
    
    # 2. 创建修正后的新记忆
    corrected = MemoryItem(
        id=str(uuid4()),
        content_class=original.content_class,
        content=new_content,
        source="user_correction",
        confidence=1.0,  # 用户确认，置信度为1
        status="active",
        visibility="durable",
        created_at=utc_now(),
        updated_at=utc_now(),
        metadata={
            **original.metadata,
            "corrected_from": memory_id,
            "correction_reason": reason,
        },
    )
    
    # 3. 将原始记忆标记为 superseded
    await self._mark_superseded(user_id, memory_id, "user_corrected")
    
    # 4. 写入新记忆
    await self._write_memory_item(user_id, corrected)
    
    # 5. 记录治理事件
    await self._journal_governance_event(
        user_id=user_id,
        action="correct",
        target_id=memory_id,
        new_id=corrected.id,
        reason=reason,
    )
    
    return MemoryCorrectionResult(
        success=True,
        original_id=memory_id,
        new_id=corrected.id,
    )
```

### 5.4 删除记忆

```python
async def delete_memory(
    self,
    user_id: str,
    memory_id: str,
    reason: str | None = None,
) -> MemoryDeletionResult:
    """
    删除记忆
    - 记忆标记 governance metadata
    - 读取时默认不显示已删除内容
    - 匹配的世界模型候选被回滚
    """
    
    # 1. 获取记忆
    memory = await self._get_memory_item(user_id, memory_id)
    
    # 2. 标记为已删除
    await self._mark_deleted(user_id, memory_id, reason)
    
    # 3. 如果是关系记忆，在图谱中失效
    if memory.content_class == ContentClass.RELATIONSHIP:
        await self.graph_store.supersede_relation(
            subject=memory.metadata.get("subject"),
            predicate=memory.metadata.get("predicate"),
            reason="governance_delete",
        )
    
    # 4. 回滚相关候选
    await self._rollback_related_candidates(user_id, memory_id, reason)
    
    # 5. 记录治理事件
    await self._journal_governance_event(
        user_id=user_id,
        action="delete",
        target_id=memory_id,
        reason=reason,
    )
    
    return MemoryDeletionResult(success=True, deleted_id=memory_id)
```

### 5.5 阻止学习

```python
async def block_learning(
    self,
    user_id: str,
    content_class: ContentClass,
    block: bool = True,
) -> GovernancePolicyUpdate:
    """
    阻止指定内容类别的未来学习
    - 不影响现有记忆（除非单独删除/修正）
    - 影响待处理候选
    """
    
    # 1. 获取当前策略
    policy = await self.core_memory_store.get_governance_policy(user_id)
    
    # 2. 更新阻塞列表
    if block:
        policy.blocked_content_classes.add(content_class)
    else:
        policy.blocked_content_classes.discard(content_class)
    
    policy.updated_at = utc_now()
    
    # 3. 保存策略
    await self.core_memory_store.save_governance_policy(user_id, policy)
    
    # 4. 如果是阻止，回滚该类别的待处理候选
    if block:
        await self._rollback_candidates_by_class(user_id, content_class)
    
    # 5. 记录治理事件
    await self._journal_governance_event(
        user_id=user_id,
        action="block_learning",
        target_class=content_class,
        blocked=block,
    )
    
    return GovernancePolicyUpdate(
        success=True,
        content_class=content_class,
        blocked=block,
    )
```

### 5.6 修剪过期记忆

```python
async def prune_expired(
    self,
    user_id: str,
) -> PruneResult:
    """
    修剪过期的推断/待确认/冲突/候选条目
    - 事实保留由读取时过滤处理
    - 其他类型在写入时修剪
    """
    
    pruned_count = 0
    
    # 修剪过期推断
    expired_inferences = await self._get_expired_inferences(
        user_id,
        retention=DEFAULT_RETENTION_POLICY[ContentClass.INFERENCE],
    )
    for item in expired_inferences:
        await self._soft_delete(user_id, item.id)
        pruned_count += 1
    
    # 修剪过期待确认
    expired_pending = await self._get_expired_pending(
        user_id,
        retention=SPECIAL_RETENTION["pending_confirmations"],
    )
    for item in expired_pending:
        await self._soft_delete(user_id, item.id)
        pruned_count += 1
    
    # 修剪过期冲突
    expired_conflicts = await self._get_expired_conflicts(
        user_id,
        retention=SPECIAL_RETENTION["memory_conflicts"],
    )
    for item in expired_conflicts:
        await self._soft_delete(user_id, item.id)
        pruned_count += 1
    
    return PruneResult(pruned_count=pruned_count)
```

---

## 6. 修正语义

### 6.1 修正原则

Phase 21 的记忆修正是**替换而非覆盖**：

```
修正前
     ↓
记忆A (content="用户喜欢Python", confidence=0.8)
     ↓
用户修正：content="用户更喜欢JavaScript"
     ↓
修正后
     ↓
记忆A' (content="用户更喜欢JavaScript", source="user_correction", confidence=1.0)
     ↓
记忆A (content="用户喜欢Python", status="superseded")
```

### 6.2 修正语义保证

| 保证 | 说明 |
|------|------|
| **原始保留** | 原始记忆被标记为 superseded，不删除 |
| **用户确认** | 新记忆 source="user_correction"，置信度=1.0 |
| **元数据传递** | corrected_from 指向原始记忆 |
| **候选回滚** | 如果有相关候选，标记为 reverted |
| **审计记录** | 所有修正记录到 journal |

---

## 7. 删除语义

### 7.1 删除原则

Phase 21 的记忆删除是**软删除 + 候选回滚**：

```
删除记忆A
     ↓
记忆A (status="deleted", governance_delete=True)
     ↓
读取时默认不显示
     ↓
如果A是关系 → 图谱中失效
     ↓
相关候选 → 标记 reverted (reason="governance_delete")
     ↓
治理事件 → journal 记录
```

### 7.2 删除语义保证

| 保证 | 说明 |
|------|------|
| **软删除** | 标记为 deleted，不物理删除 |
| **默认隐藏** | 读取时 exclude deleted |
| **关系失效** | 如果是关系，在 GraphStore 中失效 |
| **候选回滚** | 相关候选被 reverted |
| **审计记录** | 所有删除记录到 journal |

---

## 8. 阻止学习语义

### 8.1 阻止学习原则

Phase 21 的阻止学习**仅影响未来**：

```
阻止 learning content_class=inference
     ↓
现有推断记忆 → 不受影响
     ↓
未来新推断 → 不创建
     ↓
待处理候选 → 回滚
```

### 8.2 阻止学习保证

| 保证 | 说明 |
|------|------|
| **仅未来** | 不影响现有记忆 |
| **待处理候选** | 该类别的 pending 候选被 reverted |
| **可选恢复** | unblock_learning 可恢复 |

---

## 9. 用户-facing API

### 9.1 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/memory` | GET | 列表用户记忆 |
| `/memory/governance` | GET | 获取治理策略 |
| `/memory/governance` | PUT/PATCH | 更新治理策略 |
| `/memory/correct` | POST | 修正记忆 |
| `/memory/delete` | POST | 删除记忆 |
| `/memory/governance/block` | POST | 阻止/恢复学习 |

### 9.2 GET /memory

```python
@router.get("/memory")
async def list_memory(
    user_id: str,
    content_class: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> MemoryListResponse:
    """
    列表用户的世界模型记忆
    - 默认不包含已删除记忆
    - 支持按类别过滤
    - 支持按状态过滤
    """
    items = await governance_service.list_memory(
        user_id=user_id,
        content_class=content_class,
        status=status,
        include_deleted=include_deleted,
    )
    
    return MemoryListResponse(
        items=items,
        total=len(items),
    )
```

### 9.3 POST /memory/correct

```python
class MemoryCorrectRequest(BaseModel):
    memory_id: str
    new_content: str
    reason: str | None = None


@router.post("/memory/correct")
async def correct_memory(
    user_id: str,
    request: MemoryCorrectRequest,
) -> MemoryCorrectionResponse:
    """
    修正记忆
    - 原始记忆被 superseded
    - 新记忆 source="user_correction"
    """
    result = await governance_service.correct_memory(
        user_id=user_id,
        memory_id=request.memory_id,
        new_content=request.new_content,
        reason=request.reason,
    )
    
    return MemoryCorrectionResponse(
        success=result.success,
        original_id=result.original_id,
        new_id=result.new_id,
    )
```

### 9.4 POST /memory/delete

```python
class MemoryDeleteRequest(BaseModel):
    memory_id: str
    reason: str | None = None


@router.post("/memory/delete")
async def delete_memory(
    user_id: str,
    request: MemoryDeleteRequest,
) -> MemoryDeletionResponse:
    """
    删除记忆
    - 软删除 + 候选回滚
    """
    result = await governance_service.delete_memory(
        user_id=user_id,
        memory_id=request.memory_id,
        reason=request.reason,
    )
    
    return MemoryDeletionResponse(
        success=result.success,
        deleted_id=result.deleted_id,
    )
```

### 9.5 POST /memory/governance/block

```python
class MemoryBlockRequest(BaseModel):
    content_class: ContentClass
    block: bool = True


@router.post("/memory/governance/block")
async def block_learning(
    user_id: str,
    request: MemoryBlockRequest,
) -> GovernanceBlockResponse:
    """
    阻止/恢复指定内容类别的未来学习
    """
    result = await governance_service.block_learning(
        user_id=user_id,
        content_class=request.content_class,
        block=request.block,
    )
    
    return GovernanceBlockResponse(
        success=result.success,
        content_class=result.content_class,
        blocked=result.blocked,
    )
```

### 9.6 GET /memory/governance

```python
@router.get("/memory/governance")
async def get_governance_policy(
    user_id: str,
) -> GovernancePolicyResponse:
    """
    获取用户的记忆治理策略
    """
    policy = await governance_service.get_policy(user_id)
    
    return GovernancePolicyResponse(
        blocked_content_classes=list(policy.blocked_content_classes),
        retention_days=policy.retention_days,
        updated_at=policy.updated_at,
    )
```

---

## 10. CognitionUpdater 集成

### 10.1 阻止类别检查

Phase 21 的 CognitionUpdater 在创建候选前检查阻塞类别：

```python
async def _handle_world_model_lesson(
    self,
    lesson: dict,
) -> None:
    """处理世界模型 lesson"""
    
    # 1. 确定内容类别
    content_class = self._classify_world_model_content(lesson)
    
    # 2. Phase 21 新增：检查是否被阻止
    policy = await self.core_memory_store.get_governance_policy(lesson["user_id"])
    
    if content_class in policy.blocked_content_classes:
        # 阻止学习，不创建候选
        await self._journal_blocked_lesson(
            lesson=lesson,
            reason=f"content_class {content_class} is blocked",
        )
        return
    
    # 3. 正常创建候选
    await self.candidate_manager.submit(
        ...
    )
```

### 10.2 阻止行为

```python
async def _journal_blocked_lesson(
    self,
    lesson: dict,
    reason: str,
) -> None:
    """记录被阻止的 lesson"""
    
    await self.evolution_journal.record(
        event_type="lesson_blocked_by_governance",
        user_id=lesson["user_id"],
        details={
            "lesson_content": lesson.get("content"),
            "content_class": self._classify_world_model_content(lesson),
            "reason": reason,
        },
    )
```

---

## 11. CoreMemoryScheduler 集成

### 11.1 写入时修剪

Phase 21 的 CoreMemoryScheduler 在写入前修剪治理记忆：

```python
async def rebuild_world_model(
    self,
    user_id: str,
) -> WorldModel:
    """重建世界模型"""
    
    # 1. 清理过期/治理删除的记忆
    await self.governance_service.prune_expired(user_id)
    
    # 2. 重建其他部分
    world_model = await self._rebuild_world_model_parts(user_id)
    
    # 3. 确保治理策略被保留
    world_model.memory_governance = await self.core_memory_store.get_governance_policy(user_id)
    
    return world_model
```

### 11.2 快照保留治理策略

```python
async def save_snapshot(
    self,
    user_id: str,
    world_model: WorldModel,
) -> None:
    """保存快照"""
    
    # 确保 memory_governance 被保存
    if not world_model.memory_governance:
        world_model.memory_governance = await self.core_memory_store.get_governance_policy(user_id)
    
    await self.core_memory_store.save_snapshot(user_id, world_model)
```

---

## 12. GraphStore 关系失效支持

### 12.1 关系失效

Phase 21 的 GraphStore 支持治理删除/修正导致的失效：

```python
async def supersede_relation(
    self,
    subject: str,
    predicate: str,
    reason: str,
) -> None:
    """
    失效关系
    - 用于治理删除/修正
    """
    
    # 1. 查找现有关系
    existing = await self.get_relation(subject, predicate)
    
    if existing:
        # 2. 标记为 superseded
        existing.status = "superseded"
        existing.governance_superseded = True
        existing.superseded_reason = reason
        
        # 3. 写入历史
        await self._write_history_entry(existing)
        
        # 4. 删除活跃关系
        await self._delete_active_relation(subject, predicate)
```

---

## 13. 运行时连接

### 13.1 Bootstrap 更新

Phase 21 的运行时连接：

```python
async def bootstrap_runtime() -> RuntimeContext:
    # ... Phase 20 组件 ...
    
    # Phase 21 新增：记忆治理服务
    memory_governance_service = MemoryGovernanceService(
        core_memory_store=core_memory_store,
        graph_store=graph_store,
        candidate_manager=candidate_manager,
        evolution_journal=evolution_journal,
    )
    
    return RuntimeContext(
        # ...
        memory_governance_service=memory_governance_service,
    )
```

### 13.2 健康快照扩展

```python
def health_snapshot(self) -> dict[str, Any]:
    subsystems = {
        # ...
        "memory_governance": {
            "status": "ok",
            "memory_governance_enabled": True,
            "memory_governance_degraded": self.memory_governance_service.degraded,
        },
    }
```

---

## 14. 验证与验收

### 14.1 验证命令

```bash
# Phase 21 专项测试
python -m pytest tests/test_api_routes.py \
  tests/test_memory_governance.py \
  tests/test_relationship_memory.py \
  tests/test_runtime_bootstrap.py \
  tests/test_failure_semantics.py \
  tests/test_observability.py \
  tests/test_integration_runtime.py

# 完整测试套件
python -m pytest

# 字节码编译检查
python -m compileall app tests
```

### 14.2 验收检查项

- [ ] 105 个测试全部通过（Phase 20 的 96 + Phase 21 新增）
- [ ] `test_memory_governance.py` 存在且覆盖关键路径
- [ ] MemoryGovernancePolicy 数据结构正确
- [ ] 默认保留策略正确定义
- [ ] MemoryGovernanceService 正确实现
- [ ] GET /memory 正确列表记忆
- [ ] POST /memory/correct 正确修正（替换而非覆盖）
- [ ] POST /memory/delete 正确删除（软删除 + 候选回滚）
- [ ] POST /memory/governance/block 正确阻止学习
- [ ] GET /memory/governance 正确返回策略
- [ ] CognitionUpdater 正确检查阻塞类别
- [ ] CoreMemoryScheduler 正确修剪治理记忆
- [ ] GraphStore 正确失效关系
- [ ] 运行时正确注入治理服务
- [ ] `/health` 正确暴露治理状态
- [ ] journal 正确记录治理事件

### 14.3 测试覆盖

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_memory_governance.py` | Phase 21 新增，测试治理服务全流程 |
| `tests/test_api_routes.py` | 更新覆盖 /memory 端点 |

---

## 15. Explicitly Not Done Yet

以下功能在 Phase 21 中**仍未完成**：

- [ ] 用户-facing 记忆治理仪表板或 admin UI
- [ ] 批量导出/导入治理工作流
- [ ] personality、self-cognition 或 relationship-style 状态的治理控制
- [ ] 读取/写入路径执行之外的的后台修剪调度器
- [ ] 多租户或组织级治理策略层

---

## 16. Phase 21 的意义

### 16.1 从"系统自治"到"用户主导"

Phase 21 完成后，系统从"系统自治"升级到"用户主导"：

```
Phase 20 之前
     ↓
记忆系统自主积累
     ↓
用户无法控制
     ↓
透明度缺失

Phase 21 新增
     ↓
用户记忆治理 API
     ↓
用户可查看/修正/删除/阻止
     ↓
用户主导记忆
```

### 16.2 修正/删除原则

Phase 21 确立了修正/删除的核心原则：

```
修正 = 替换而非覆盖
     ↓
原始保留为 superseded
     ↓
新记忆 source="user_correction"
     ↓
审计可追溯

删除 = 软删除 + 候选回滚
     ↓
治理元数据标记
     ↓
相关候选 reverted
     ↓
journal 审计
```

### 16.3 为未来 Phase 奠定基础

Phase 21 建立的记忆治理是后续 Phase 的基石：

- 记忆治理 UI → 基于现有 API
- 批量导出/导入 → 基于现有治理结构
- 更丰富治理策略 → 扩展 MemoryGovernancePolicy
- 多租户治理 → 基于现有用户级治理扩展

### 16.4 关键设计原则

Phase 21 确立的关键设计原则：

| 原则 | 说明 |
|------|------|
| **治理边界** | 仅治理世界模型记忆，不触及 self_cognition/personality |
| **替换而非覆盖** | 修正时原始记忆标记为 superseded |
| **软删除 + 回滚** | 删除标记 + 相关候选 reverted |
| **仅影响未来** | 阻止学习不追溯现有记忆 |
| **审计可见** | 所有治理操作记录到 journal |
| **可见性分离** | durable vs candidate 区分 |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[LONG_TERM_COMPANION_PLAN.md|LONG_TERM_COMPANION_PLAN]] — 长期陪伴计划
- [[Phase-20-学习笔记]] — 关系状态机
- [[../phase_21_status.md|phase_21_status.md]] — Phase 21 给 Codex 的状态文档
