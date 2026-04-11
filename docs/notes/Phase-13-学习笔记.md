# Phase 13 学习笔记：检索与记忆质量

> **前置阶段**：[[Phase-12-学习笔记]]  
> **目标**：强化向量检索行为稳定性，修复 prompt 生成对 Python dataclass repr 的脆弱依赖，提升记忆质量  
> **里程碑**：本阶段完成后检索结果更稳定可靠，prompt 生成不再依赖运行时内部实现细节

---

## 目录

- [概述](#概述)
- [1. Phase 13 文件清单](#1-phase-13-文件清单)
- [2. 为什么需要检索与记忆质量](#2-为什么需要检索与记忆质量)
- [3. VectorRetriever 检索稳定性](#3-vectorretriever-检索稳定性)
- [4. Rerank 合并语义保守化](#4-rerank-合并语义保守化)
- [5. Prompt 生成重构](#5-prompt-生成重构)
- [6. 内存块空值处理](#6-内存块空值处理)
- [7. 验证与验收](#7-验证与验收)
- [8. 设计原则](#8-设计原则)
- [9. Explicitly Not Done Yet](#9-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 13 的目标是**提升检索与记忆的质量稳定性**。

Phase 12 实现了真实网页搜索，Phase 13 则关注系统内部记忆的检索质量和 prompt 生成稳定性。

### Phase 12 到 Phase 13 的演进

Phase 12 之后发现了两个问题：

1. **检索稳定性问题**：
   - Rerank 输出处理不够安全
   - 部分 rerank 结果可能丢失未重新排序的记忆
   - 格式错误的 rerank 索引会导致崩溃

2. **Prompt 生成脆弱性**：
   - `SoulEngine` 直接使用 Python dataclass 的 `__repr__` 输出
   - Python 版本或运行时变化可能改变 repr 格式
   - 空记忆块渲染不一致

Phase 13 修复了这两个问题。

### 新的系统形态

```
SoulEngine.run()
    ↓
┌─ 记忆检索 ──────────────────────┐
│ VectorRetriever.retrieve()        │
│   ├─ 原始召回 matches              │
│   └─ rerank 排序（variance-gated）│
│       └─ 保守合并：                │
│           reranked subset        │
│           + unre-ranked recalled │
└─────────────────────────────────┘
    ↓
┌─ Prompt 组装 ──────────────────┐
│ 显式格式化 self_cognition        │
│ 显式格式化 world_model          │
│ 显式格式化 task_experience       │
│ 空块 → 稳定 fallback 字符串      │
└─────────────────────────────────┘
```

---

## 1. Phase 13 文件清单

| 文件 | 内容 |
|------|------|
| `app/memory/vector_retriever.py` | 强化检索行为，稳定 rerank 合并语义 |
| `app/soul/engine.py` | 移除 dataclass repr 依赖，显式格式化 prompt |
| `tests/test_vector_retriever.py` | 检索专项回归测试 |
| `tests/test_soul_engine.py` | Prompt 质量断言测试 |

---

## 2. 为什么需要检索与记忆质量

### 2.1 之前的问题

Phase 12 之后的检索和 prompt 存在以下问题：

**检索稳定性问题**：

- Rerank 输出与原始召回结果合并时可能丢失数据
- 部分 rerank 结果导致未 rerank 的记忆被丢弃
- 格式错误的 rerank 索引没有安全回退

**Prompt 生成脆弱性问题**：

```python
# 之前：直接使用 dataclass repr
prompt = f"Self认知: {self_cognition}"
```

Python dataclass 的 `__repr__` 输出**不是稳定的 API**：

- 不同 Python 版本格式可能不同
- 字段顺序在不同版本中可能变化
- 嵌套对象可能产生不同输出

**空值处理不一致**：

- 空 memory block 可能产生不同格式的空输出
- Prompt 内容在不同运行时不可预测

### 2.2 质量稳定性的价值

稳定的检索和 prompt 生成确保：

- **一致性**：相同输入产生相同输出
- **可预测性**：Prompt 内容可被可靠地调试和测试
- **跨版本兼容**：Python 升级不影响核心行为
- **正确性**：Rerank 结果不会意外丢失记忆

---

## 3. VectorRetriever 检索稳定性

### 3.1 `VectorRetriever.retrieve()` 响应契约

Phase 13 **保持不变**的响应契约：

```python
{
    "core_memory": [...],  # 核心记忆
    "matches": [...]        # 检索匹配结果
}
```

契约稳定意味着：

- 上游消费者（如 `SoulEngine`）不需要修改
- 后续 phases 可以依赖这个契约

### 3.2 Rerank 分级触发

```python
# Phase 13 保持 variance-gated 设计
if self._should_rerank(query, matches):
    reranked = self._rerank(query, matches)
    matches = self._merge_rerank_results(matches, reranked)
```

Rerank 不是每次都触发，而是根据方差判断是否有必要。

### 3.3 Rerank 输出处理

Phase 13 修复了 rerank 输出的合并逻辑：

```python
def _merge_rerank_results(
    recalled: list[Match],
    reranked: list[RerankedMatch]
) -> list[Match]:
    # 收集所有被 rerank 的索引
    reranked_ids = {r.index for r in reranked if r.index < len(recalled)}
    
    # reranked 子集按 rerank score 降序排列
    reranked_subset = sorted(
        [recalled[r.index] for r in reranked if r.index < len(recalled)],
        key=lambda m: m.score,
        reverse=True
    )
    
    # 未被 rerank 的 recalled 项保留原顺序
    unre_ranked_recalled = [
        m for i, m in enumerate(recalled) 
        if i not in reranked_ids
    ]
    
    # 合并：reranked subset + unre_ranked recalled
    return reranked_subset + unre_ranked_recalled
```

---

## 4. Rerank 合并语义保守化

### 4.1 合并原则

Phase 13 的 rerank 合并遵循**保守原则**：

| 原则 | 说明 |
|------|------|
| **不丢弃** | 未被 rerank 的 recalled matches 不会被丢弃 |
| **稳定排序** | reranked subset 按 rerank score 降序 |
| **安全回退** | 格式错误的 rerank 索引回退到原始召回顺序 |

### 4.2 格式错误的 Rerank 索引安全回退

```python
def _safe_merge_rerank_results(
    recalled: list[Match],
    reranked: list[RerankedMatch]
) -> list[Match]:
    valid_reranked = []
    invalid_indices = []
    
    for r in reranked:
        if 0 <= r.index < len(recalled):
            valid_reranked.append(r)
        else:
            invalid_indices.append(r.index)
    
    if invalid_indices:
        # 记录警告，使用保守回退
        logger.warning(
            "rerank_invalid_indices",
            indices=invalid_indices,
            fallback="original_recall_order"
        )
        return recalled  # 完全回退到原始顺序
    
    # 正常合并逻辑
    ...
```

### 4.3 为什么保守

保守合并的原因：

- **数据完整性**：记忆不能丢失
- **可预测性**：检索结果应该反映尽可能多的相关记忆
- **容错性**：rerank 服务异常时不应影响基本检索功能

---

## 5. Prompt 生成重构

### 5.1 之前的问题

Phase 13 之前，`SoulEngine` 直接使用 dataclass repr 生成 prompt：

```python
# 之前（脆弱）
prompt = f"""
Self Cognition:
{self_cognition}  # 依赖 __repr__

World Model:
{world_model}     # 依赖 __repr__

Task Experience:
{task_experience}  # 依赖 __repr__
"""
```

这有以下问题：

- `__repr__` 格式不稳定
- 空值输出不确定
- 难以测试 prompt 内容

### 5.2 显式格式化

Phase 13 为每种记忆类型实现了显式格式化：

```python
def _format_self_cognition(self, cognition: SelfCognition) -> str:
    if cognition is None or cognition.is_empty():
        return "[Self Cognition: No information available]"
    
    lines = [
        f"Identity: {cognition.identity}",
        f"Capabilities: {cognition.capabilities}",
        f"Constraints: {cognition.constraints}",
    ]
    return "\n".join(filter(None, lines))


def _format_world_model(self, model: WorldModel) -> str:
    if model is None or model.is_empty():
        return "[World Model: No information available]"
    
    lines = [
        f"User Preferences: {model.user_preferences}",
        f"Recent Context: {model.recent_context}",
        f"Domain Knowledge: {model.domain_knowledge}",
    ]
    return "\n".join(filter(None, lines))


def _format_task_experience(self, experience: TaskExperience) -> str:
    if experience is None or experience.is_empty():
        return "[Task Experience: No information available]"
    
    lines = [
        f"Completed Tasks: {experience.completed_count}",
        f"Failed Tasks: {experience.failed_count}",
        f"Recent Lessons: {experience.recent_lessons}",
    ]
    return "\n".join(filter(None, lines))
```

### 5.3 好处

显式格式化的好处：

| 方面 | 说明 |
|------|------|
| **稳定性** | 不依赖 Python 内部实现 |
| **可测试性** | 可以精确断言 prompt 内容 |
| **可读性** | 格式化逻辑清晰可见 |
| **可控性** | 空值处理明确，不会产生垃圾输出 |

---

## 6. 内存块空值处理

### 6.1 之前的问题

空 memory block 之前可能产生：

- `None`
- 空字符串 `""`
- Python repr 的空对象如 `<SelfCognition []>`

这些都让 prompt 内容不可预测。

### 6.2 稳定 Fallback 字符串

Phase 13 为空内存块定义了一致的 fallback：

```python
FALLBACK_STRINGS = {
    "self_cognition": "[Self Cognition: No information available]",
    "world_model": "[World Model: No information available]",
    "task_experience": "[Task Experience: No information available]",
}
```

### 6.3 设计理由

稳定 fallback 的价值：

- **Prompt 内容可预测**：即使没有记忆，prompt 格式也一致
- **便于调试**：看到固定字符串就知道是缺少哪类记忆
- **避免垃圾输出**：不会产生难以理解的空值表示

---

## 7. 验证与验收

### 7.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 7.2 验收检查项

- [ ] 53 个测试全部通过（Phase 12 的 43 + Phase 13 新增）
- [ ] `VectorRetriever.retrieve()` 契约保持不变
- [ ] Rerank 合并不丢失未 rerank 的 recalled matches
- [ ] 格式错误的 rerank 索引正确回退到原始顺序
- [ ] `SoulEngine` 不再使用 dataclass repr
- [ ] Self cognition、world model、task experience 都有显式格式化
- [ ] 空 memory block 使用稳定的 fallback 字符串
- [ ] Prompt 内容可以被精确断言

### 7.3 明确不会做的事

Phase 13 **不会**做以下事情：

- 存储后端重新设计
- Token 预算感知的记忆块截断
- 检索匹配的去重或新鲜度加权
- 大记忆段的更丰富 prompt 压缩
- 跨存储检索融合

---

## 8. 设计原则

### 8.1 契约稳定性

`VectorRetriever.retrieve()` 的响应契约是**不可随意更改的**：

- 上游消费者依赖这个契约
- 更改契约需要明确的迁移计划
- Phase 13 专注于内部实现的稳定化

### 8.2 保守合并

Rerank 结果合并遵循**保守原则**：

- 未 rerank 的项不被丢弃
- 异常时回退到已知正确的状态
- 不引入可能丢失数据的优化

### 8.3 Prompt 即代码

Prompt 生成应该**像代码一样可靠**：

- 不依赖运行时内部实现
- 显式格式化逻辑可读、可测试
- 空值处理明确、可预测

### 8.4 方差触发

Rerank 不是每次都执行，而是**方差触发的**：

- 减少不必要的 rerank 调用
- 节省计算资源
- 只在值得优化时优化

---

## 9. Explicitly Not Done Yet

以下功能在 Phase 13 中**仍未完成**：

- [ ] 存储后端重新设计
- [ ] Token 预算感知的记忆块截断
- [ ] 检索匹配的去重或新鲜度加权
- [ ] 大记忆段的更丰富 prompt 压缩
- [ ] 跨存储检索融合

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-12-学习笔记]] — WebAgent 真实搜索实现
- [[../phase_13_status.md|phase_13_status.md]] — Phase 13 给 Codex 的状态文档
