# Phase 10 学习笔记：运行时正确性与失败语义

> **前置阶段**：[[Phase-9-学习笔记]]  
> **目标**：强化事件总线、Outbox Relay、Worker、Blackboard 的失败处理语义，确保运行时在各种故障场景下行为可预期  
> **里程碑**：本阶段完成后系统具备明确的失败分类处理机制，不再混淆可恢复失败与不可恢复失败

---

## 目录

- [概述](#概述)
- [1. Phase 10 文件清单](#1-phase-10-文件清单)
- [2. 失败语义的必要性](#2-失败语义的必要性)
- [3. 事件反序列化失败处理](#3-事件反序列化失败处理)
- [4. 事件处理器失败处理](#4-事件处理器失败处理)
- [5. 幂等性持久化失败处理](#5-幂等性持久化失败处理)
- [6. Outbox Relay 降级语义](#6-outbox-relay-降级语义)
- [7. Worker 任务状态保护](#7-worker-任务状态保护)
- [8. Blackboard 失败事件改进](#8-blackboard-失败事件改进)
- [9. Runtime Health 增强](#9-runtime-health-增强)
- [10. 降级规则汇总](#10-降级规则汇总)
- [11. 验证与验收](#11-验证与验收)
- [12. 设计原则](#12-设计原则)
- [13. Explicitly Not Done Yet](#13-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 10 的目标是**建立清晰的失败语义**，让系统在各种故障场景下行为可预期。

Phase 9 建立了测试基础设施，Phase 10 则利用这套基础设施来强化核心组件的失败处理。

### Phase 9 到 Phase 10 的演进

Phase 9 的测试发现了以下问题：

- 事件反序列化失败时系统行为不确定
- 事件处理器失败时消息未被正确确认，导致无限重试
- 幂等性状态持久化失败时无法保证正确性
- Outbox Relay 在 Redis 不可用时错误地标记事件为已发布
- Worker 的 `interrupted` / `cancelled` 状态被错误地合并为 `failed`
- Runtime health 信息不够完整

Phase 10 逐一修复了这些问题。

### 新的系统形态

Phase 10 之后，失败处理有了明确的分类：

```
失败场景
    ↓
分类判断
    ↓
├─ 不可恢复失败（malformed payload）
│       └─ ACK 消息，避免无限重试
│
├─ 可恢复失败（handler 执行异常）
│       └─ 保持 unacked，保留重试可能
│
├─ 幂等性失败（持久化异常）
│       └─ 保持 unacked，等待 bookkeeping 成功
│
└─ 服务不可用（Redis 断开）
        └─ 跳过发布，保持 outbox pending
```

---

## 1. Phase 10 文件清单

| 文件 | 内容 |
|------|------|
| `app/evolution/event_bus.py` | 强化事件反序列化失败和处理器失败的语义 |
| `app/tasks/outbox_relay.py` | 修正 Redis 不可用时的降级语义 |
| `app/tasks/worker.py` | 保留 `interrupted` / `cancelled` 终端状态 |
| `app/tasks/blackboard.py` | 扩展失败状态处理，emit 明确终端状态 |
| `app/runtime/bootstrap.py` | 增强 runtime health，包含更多子系统状态 |
| `tests/test_failure_semantics.py` | Phase 10 针对性失败语义测试 |

---

## 2. 失败语义的必要性

### 2.1 之前的问题

在 Phase 10 之前，失败处理存在混淆：

- **不可恢复失败**（如消息格式损坏）被当作可重试失败处理，导致无限重试
- **可恢复失败**（如处理器临时异常）没有明确的恢复路径
- **幂等性失败**（如 Redis 写入失败）没有明确的行为保证

### 2.2 失败分类

Phase 10 明确将失败分为两类：

| 类型 | 特征 | 处理方式 |
|------|------|---------|
| **不可恢复失败** | 消息格式损坏、无法解析 | ACK 消息，跳过处理 |
| **可恢复失败** | 处理器执行异常、外部依赖临时不可用 | 保持 unacked，保留重试 |

### 2.3 为什么分类重要

错误的失败处理会导致：

- **无限重试循环**：损坏的消息无法通过重试修复
- **数据丢失**：消息未被正确 ACK 但被当作已处理
- **状态不一致**：幂等性记录与实际处理状态不匹配

---

## 3. 事件反序列化失败处理

### 3.1 之前的问题

当事件 payload 无法反序列化时（如 JSON 格式损坏），之前的行为不明确：

- 可能无限重试
- 可能未 ACK 导致消息卡在 pending

### 3.2 Phase 10 的修复

```python
async def _handle_message(...):
    try:
        event = self._deserialize(raw)
    except Exception:
        logger.warning(f"Malformed event payload: {raw}")
        await self._ack(message_id)
        return  # 不重试，因为 payload 不可恢复
```

关键行为：

- **记录警告日志**：保留故障现场
- **ACK 消息**：确认已处理（虽然处理方式是丢弃）
- **不重试**：因为 payload 损坏，重试也无济于事

### 3.3 设计理由

消息格式损坏意味着：

- 消息本身无法修复
- 无限重试只会浪费资源
- ACK 后消息离开 stream，系统继续处理后续消息

---

## 4. 事件处理器失败处理

### 4.1 之前的问题

当事件处理器执行抛出异常时，之前的处理可能：

- 未记录错误详情
- 未正确处理消息状态

### 4.2 Phase 10 的修复

```python
try:
    await handler(event)
except Exception:
    logger.exception(f"Handler failed for event {event.id}")
    # 不 ACK，保留重试可能
    # 不标记幂等性完成
    return
```

关键行为：

- **记录异常详情**：包含完整堆栈
- **保持 unacked**：消息保留在 stream 中
- **不标记幂等性完成**：确保重试时幂等性保护仍然有效
- **后续可通过 stream recovery 重新投递**

### 4.3 设计理由

处理器失败通常是**可恢复的**：

- 外部服务临时不可用
- 资源暂时不足
- 并发冲突

这些情况重试可能会成功，所以需要保留消息的重试机会。

---

## 5. 幂等性持久化失败处理

### 5.1 之前的问题

幂等性记录（idempotency claim / mark-done）需要持久化。如果持久化失败：

- 消息被当作已处理，但记录丢失
- 重试时可能重复执行

### 5.2 Phase 10 的修复

```python
try:
    await self.idempotency_store.claim(scope, event.id)
except Exception:
    logger.exception("Idempotency claim failed")
    # 不 ACK，保留重试
    return

try:
    await handler(event)
    await self.idempotency_store.mark_done(scope, event.id)
except Exception:
    logger.exception("Idempotency mark-done failed")
    # 不 ACK，保留重试
    # completion 未被确认，直到 bookkeeping 成功
    return
```

关键行为：

- **claim 失败**：保持 unacked
- **mark-done 失败**：保持 unacked
- **直到 bookkeeping 成功，completion 才被确认**

### 5.3 设计理由

幂等性是**正确性的保障**：

- 如果不能保证幂等性，重试可能导致重复执行
- 失败时保守处理比错误确认更安全
- 日志记录确保问题可追溯

---

## 6. Outbox Relay 降级语义

### 6.1 之前的问题

当 Redis 不可用时，`OutboxRelay` 之前可能：

- 错误地标记 outbox 事件为已发布
- 导致事件丢失

### 6.2 Phase 10 的修复

```python
async def _publish_pending(self):
    if self.redis_client is None:
        logger.info("Redis unavailable, skipping publish")
        return  # 不标记为 published，保持 pending

    try:
        await self.redis_client.xadd(...)
        self.outbox_store.mark_published(event.id)
    except Exception:
        logger.warning("Redis publish failed, event remains pending")
        # 事件保持 pending 状态，不会丢失
```

关键行为：

- **Redis 不可用时跳过发布**：不假装成功
- **保持 outbox 事件为 pending**：等待 Redis 恢复后重试
- **日志记录**：便于排查

### 6.3 设计理由

Outbox 模式的核心是**至少一次语义**：

- 事件必须最终被投递
- 在 Redis 恢复前，事件应该保留在 PostgreSQL outbox 中
- 错误地标记为已发布会导致事件永久丢失

---

## 7. Worker 任务状态保护

### 7.1 之前的问题

`TaskWorker` 在处理 `interrupted` / `cancelled` 状态时：

- 被错误地合并为 `failed`
- 丢失了任务被中断/取消的语义

### 7.2 Phase 10 的修复

```python
async def _do_run(self, task: Task) -> None:
    try:
        result = await self._execute_task(task)
        await self._complete_task(task, result)
    except TaskInterruptedError:
        await self._complete_task(task, None, status="interrupted")
    except TaskCancelledError:
        await self._complete_task(task, None, status="cancelled")
    except Exception:
        await self._fail_task(task)
```

关键行为：

- **保留 `interrupted` 状态**：明确表示任务被外部中断
- **保留 `cancelled` 状态**：明确表示任务被主动取消
- **DLQ 仍会收到失败记录**：但 payload 包含明确的终端状态

### 7.3 设计理由

不同失败原因有不同的语义：

- `failed`：执行过程中出错
- `interrupted`：外部强制中断，可能需要人工介入
- `cancelled`：用户或系统主动取消

混淆这些状态会导致：

- 问题诊断困难
- 人工恢复时无法判断原始意图
- 统计和分析数据不准确

---

## 8. Blackboard 失败事件改进

### 8.1 之前的问题

`Blackboard.on_task_failed()` 之前：

- 不接受明确的终端状态
- 统一发出 `TASK_FAILED` 事件

### 8.2 Phase 10 的修复

```python
def on_task_failed(
    self,
    task_id: str,
    error: str,
    terminal_status: str = "failed"  # 新增参数
) -> None:
    # ...
    event = Event(
        type=EventType.TASK_FAILED,
        payload={
            "task_id": task_id,
            "error": error,
            "terminal_status": terminal_status,  # 明确传递
            ...
        }
    )
    self.event_bus.emit(event)
```

关键行为：

- **接受明确的 terminal_status**：可以是 `failed`、`interrupted`、`cancelled`
- **事件 payload 包含终端状态**：消费者可以区分不同失败类型

### 8.3 设计理由

失败事件的消费者可能需要区分失败类型：

- 统计分析需要准确分类
- 告警系统可能对不同失败类型有不同的处理
- 人工恢复流程需要知道失败原因

---

## 9. Runtime Health 增强

### 9.1 之前的问题

Phase 9 的 runtime health 信息不够完整：

- 缺少 `outbox_relay` 状态
- 缺少 `session_context` 状态
- 缺少 `startup_degraded_reasons`

### 9.2 Phase 10 的增强

```python
def health_snapshot(self) -> dict[str, Any]:
    return {
        "app": {...},
        "redis": {...},
        "postgres": {...},
        "outbox_relay": {  # 新增
            "degraded": self.outbox_relay.degraded if self.outbox_relay else True,
        },
        "session_context": {  # 新增
            "available": self.session_context_store is not None,
        },
        "startup_degraded_reasons": self._collect_degraded_reasons(),  # 新增
        ...
    }
```

### 9.3 `streaming_disabled` 标志

```python
def bind_runtime_state(app: FastAPI, runtime: RuntimeContext) -> None:
    if runtime.redis_client is None:
        app.state.streaming_disabled = True  # 新增：Redis 不可用时明确禁用流
```

### 9.4 设计理由

Health 信息越完整，运维和调试越方便：

- `outbox_relay` 状态：判断事件投递是否正常
- `session_context` 状态：判断会话缓存是否可用
- `startup_degraded_reasons`：启动时有哪些组件降级
- `streaming_disabled`：明确流处理是否启用

---

## 10. 降级规则汇总

### 10.1 降级矩阵

| 失败场景 | 处理行为 | 理由 |
|---------|---------|------|
| **消息 payload 损坏** | log + ACK | 不可恢复，避免无限重试 |
| **处理器执行失败** | log + 保持 unacked | 可恢复，保留重试可能 |
| **幂等性 claim 失败** | log + 保持 unacked | bookkeeping 未完成，不确认 |
| **幂等性 mark-done 失败** | log + 保持 unacked | bookkeeping 未完成，不确认 |
| **Redis 不可用** | log + 跳过发布 + 保持 pending | 事件不丢失，等待恢复 |
| **Worker 可重试失败** | 任务回到 `pending` + 发布重试事件 | 保留重试机会 |
| **Worker interrupted** | 保留终端状态 + DLQ 收到记录 | 区分失败类型 |
| **Worker cancelled** | 保留终端状态 + DLQ 收到记录 | 区分失败类型 |

### 10.2 关键原则

1. **不可恢复失败**：快速确认，避免资源浪费
2. **可恢复失败**：保留状态，等待恢复或重试
3. ** bookkeeping 失败**：保守处理，不确认直到成功
4. **服务不可用**：保持 pending，不丢失数据

---

## 11. 验证与验收

### 11.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 11.2 验收检查项

- [ ] 31 个测试全部通过（Phase 9 的 24 + Phase 10 新增）
- [ ] 事件反序列化失败时正确 ACK
- [ ] 事件处理器失败时保持 unacked
- [ ] 幂等性持久化失败时正确处理
- [ ] Redis 不可用时 outbox 事件保持 pending
- [ ] Worker 保留 `interrupted` / `cancelled` 终端状态
- [ ] Blackboard 发出包含明确终端状态的失败事件
- [ ] Runtime health 包含 `outbox_relay`、`session_context`、`startup_degraded_reasons`
- [ ] `streaming_disabled` 在 Redis 不可用时正确设置

### 11.3 明确不会做的事

Phase 10 **不会**做以下事情：

- Phase 11 的更丰富操作员面向结构化日志
- 每个失败消息的单独重试限制或毒消息隔离
- 针对 Redis Streams 和 PostgreSQL 的实时集成验证
- 端到端异步工作流测试

---

## 12. 设计原则

### 12.1 失败分类优先

处理失败的第一步是**分类**：

- 不可恢复失败（malformed）：快速丢弃
- 可恢复失败（retryable）：保留重试
- 基础设施失败（Redis down）：等待恢复

不同类型的失败需要不同的处理策略。

### 12.2 保守确认

当不确定时，**保守处理**比激进确认更安全：

- 幂等性持久化失败 → 不确认完成
- 消息处理失败 → 保持 unacked
- 服务不可用 → 不假装成功

### 12.3 状态保真

不同状态的语义应该被**保留**，而不是被合并：

- `interrupted` ≠ `failed`
- `cancelled` ≠ `failed`
- 保留原始状态便于问题诊断和统计分析

### 12.4 健康信息完整

Runtime health 应该包含**所有关键子系统**的状态，而不仅仅是数据库连接状态：

- outbox_relay
- session_context
- startup_degraded_reasons

---

## 13. Explicitly Not Done Yet

以下功能在 Phase 10 中**仍未完成**：

- [ ] 更丰富的操作员面向结构化日志（Phase 11）
- [ ] 每个失败消息的单独重试限制
- [ ] 毒消息隔离机制
- [ ] Redis Streams 和 PostgreSQL 实时集成验证
- [ ] 端到端异步工作流测试

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-9-学习笔记]] — 测试基础与安全网
- [[../phase_10_status.md|phase_10_status.md]] — Phase 10 给 Codex 的状态文档
