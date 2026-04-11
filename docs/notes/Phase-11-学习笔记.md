# Phase 11 学习笔记：可观测性与运维清晰度

> **前置阶段**：[[Phase-10-学习笔记]]  
> **目标**：增加结构化运行时日志和健康信息，提升运维人员对系统状态的可见性  
> **里程碑**：本阶段完成后运维人员可通过 `/health` 端点和结构化日志了解系统运行状况

---

## 目录

- [概述](#概述)
- [1. Phase 11 文件清单](#1-phase-11-文件清单)
- [2. 为什么需要可观测性](#2-为什么需要可观测性)
- [3. 结构化日志扩展](#3-结构化日志扩展)
- [4. Runtime Health 增强](#4-runtime-health-增强)
- [5. `/health` 端点兼容性](#5-health-端点兼容性)
- [6. 验证与验收](#6-验证与验收)
- [7. 设计原则](#7-设计原则)
- [8. Explicitly Not Done Yet](#8-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 11 的目标是**增强可观测性**，让运维人员能够清晰地了解系统运行状态。

Phase 10 建立了明确的失败语义，Phase 11 则让这些失败和系统行为变得**可见、可追踪**。

### Phase 10 到 Phase 11 的演进

Phase 10 定义了正确的失败处理行为，但没有完善的日志记录：

- 任务被分配了，但没有记录
- 任务重试被调度了，但日志不完整
- Outbox 发布成功或失败，日志不清晰
- 事件处理器失败了，但日志不够结构化

Phase 11 补充了这些可观测性基础设施。

### 新的系统形态

Phase 11 之后，运维视角的系统状态：

```
/health 端点
    ↓
├─ status: "ok" | "degraded"
├─ subsystems:
│   ├─ redis: {status, reason?}
│   ├─ postgres: {status, reason?}
│   ├─ worker: {workers, degraded_workers, reason?}
│   ├─ skill_loader: {loaded_count, skipped_count, failed_count}
│   ├─ mcp_loader: {loaded_count, skipped_count, failed_count}
│   └─ ...
├─ streaming_available: true | false
└─ startup_degraded_reasons: [...]

结构化日志
    ↓
task_assigned
task_retry_scheduled
task_dlq_published
outbox_relay_published
outbox_relay_retry_scheduled
outbox_relay_publish_skipped
runtime_startup_degraded
tool_invocation_failed
```

---

## 1. Phase 11 文件清单

| 文件 | 内容 |
|------|------|
| `app/runtime/bootstrap.py` | 增强 `health_snapshot()`，包含更丰富的运维信息 |
| `app/tasks/system.py` | 新增任务分配、重试调度、DLQ 发布的结构化日志 |
| `app/tasks/outbox_relay.py` | 新增 outbox 发布成功、跳过、重试调度的结构化日志 |
| `app/evolution/event_bus.py` | 新增事件总线降级启动的日志 |
| `app/soul/router.py` | 新增工具调用失败的日志 |
| `tests/test_observability.py` | 可观测性专项测试 |

---

## 2. 为什么需要可观测性

### 2.1 之前的问题

Phase 10 定义了正确的失败语义，但系统行为对运维人员来说是"黑盒"：

- 任务被分配了吗？不知道
- 重试被调度了多少次？不知道
- Outbox 事件发布成功了还是被跳过了？不知道
- 哪些组件在降级模式下启动？只知道大概

### 2.2 可观测性的价值

可观测性让运维人员能够：

- **快速定位问题**：通过日志了解系统状态
- **判断系统健康**：通过 `/health` 判断是否需要干预
- **追踪事件流**：通过结构化日志追踪任务/事件的完整生命周期
- **分析趋势**：通过日志数量和频率判断系统是否在退化

### 2.3 运维视角 vs 开发者视角

Phase 11 的可观测性是**面向运维**的：

| 维度 | 开发者视角 | 运维视角 |
|------|-----------|---------|
| 关注点 | 代码逻辑正确 | 系统可用性 |
| 日志 | DEBUG 级别，代码细节 | INFO/INFO+，业务事件 |
| 健康检查 | 单组件测试 | 聚合整体状态 |
| 故障排查 | 断点、单元测试 | 日志追踪、健康快照 |

---

## 3. 结构化日志扩展

### 3.1 日志框架

Phase 11 保留了既有的 JSON `structlog` 配置，只扩展了事件类型。

```python
import structlog
logger = structlog.get_logger()
```

### 3.2 新增日志事件

| 事件名 | 触发时机 | 关键字段 |
|--------|---------|---------|
| `task_assigned` | 任务被分配给 worker | `task_id`, `worker_id`, `domain` |
| `task_retry_scheduled` | 任务重试被调度 | `task_id`, `retry_count`, `delay` |
| `task_dlq_published` | 任务进入死信队列 | `task_id`, `error`, `terminal_status` |
| `outbox_relay_published` | Outbox 事件发布成功 | `event_id`, `stream` |
| `outbox_relay_retry_scheduled` | Outbox 发布重试被调度 | `event_id`, `retry_count` |
| `outbox_relay_publish_skipped` | Outbox 发布因降级被跳过 | `event_id`, `reason` |
| `runtime_startup_degraded` | 运行时在降级模式下启动 | `reasons` |
| `tool_invocation_failed` | 工具调用失败 | `tool_name`, `error` |

### 3.3 事件总线降级日志

```python
if self.degraded:
    logger.warning(
        "event_bus_degraded",
        reason="redis_unavailable",
        event_types=list(self._handlers.keys()),
    )
```

### 3.4 工具调用失败日志

```python
except Exception as e:
    logger.warning(
        "tool_invocation_failed",
        tool_name=tool_name,
        error=str(e),
    )
    return f"Tool {tool_name} failed: {e}"
```

### 3.5 设计原则

日志设计遵循以下原则：

- **结构化**：所有字段都是键值对，便于解析和搜索
- **有上下文**：包含足够定位问题的字段（task_id、event_id 等）
- **适度**：不记录每个函数调用，只记录关键业务事件
- **向后兼容**：不改变既有的 `structlog` 配置

---

## 4. Runtime Health 增强

### 4.1 之前的问题

Phase 10 的 `health_snapshot()` 信息不够完整：

- 缺少 worker 详细状态
- 缺少 skill/MCP loader 统计
- 缺少流处理可用性标志

### 4.2 Phase 11 的增强

```python
def health_snapshot(self) -> dict[str, Any]:
    snapshot = {
        "status": "ok" if self._is_healthy() else "degraded",
        "subsystems": {
            "redis": {...},
            "postgres": {...},
            "worker": {  # 增强
                "workers": len(self.workers),
                "degraded_workers": len([w for w in self.workers if w.degraded]),
            },
            "skill_loader": {  # 新增
                "loaded_count": self.skill_summary.get("loaded", 0),
                "skipped_count": self.skill_summary.get("skipped", 0),
                "failed_count": self.skill_summary.get("failed", 0),
            },
            "mcp_loader": {  # 新增
                "loaded_count": self.mcp_summary.get("loaded", 0),
                "skipped_count": self.mcp_summary.get("skipped", 0),
                "failed_count": self.mcp_summary.get("failed", 0),
            },
            ...
        },
        "streaming_available": self.redis_client is not None,  # 新增
        "startup_degraded_reasons": self._collect_degraded_reasons(),
    }
```

### 4.3 Reason 字段

子系统健康信息现在包含 `reason` 字段，说明降级原因：

```python
"redis": {
    "status": "degraded",
    "reason": "connection_failed",
}
```

这让运维人员不需要去翻日志就能知道问题所在。

### 4.4 Worker 详细状态

```python
"worker": {
    "workers": 4,
    "degraded_workers": 1,
    "degraded_reason": "opencode_unavailable",
}
```

### 4.5 Skill/MCP Loader 统计

```python
"skill_loader": {
    "loaded_count": 5,
    "skipped_count": 2,
    "failed_count": 0,
}
"mcp_loader": {
    "loaded_count": 3,
    "skipped_count": 1,
    "failed_count": 1,
}
```

---

## 5. `/health` 端点兼容性

### 5.1 兼容性保证

Phase 11 明确保持 `/health` 的向后兼容性：

| 字段 | 类型 | 说明 |
|------|------|------|
| `status` | string | `"ok"` 或 `"degraded"` |
| `subsystems` | object | 各子系统健康详情 |

### 5.2 新增字段（向后兼容）

Phase 11 以**增量方式**添加字段：

- `streaming_available`：新增字段，不影响现有解析
- `startup_degraded_reasons`：已有字段，保留
- subsystem 内部 reason：内部字段，不影响顶层结构

### 5.3 为什么只暴露 `/health`

Phase 11 只将 `/health` 作为公开运维接口：

- **简单**：单一端点，职责清晰
- **安全**：不暴露过多内部细节
- **稳定**：后续可在内部扩展，不影响 API 契约

---

## 6. 验证与验收

### 6.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 6.2 验收检查项

- [ ] 37 个测试全部通过（Phase 10 的 31 + Phase 11 新增）
- [ ] 结构化日志包含所有新增事件
- [ ] `/health` 返回完整的子系统状态
- [ ] Worker 健康信息包含 `workers` 和 `degraded_workers`
- [ ] Skill/MCP loader 健康信息包含 `loaded_count`、`skipped_count`、`failed_count`
- [ ] `streaming_available` 标志正确反映 Redis 可用性
- [ ] Subsystem 包含 `reason` 字段说明降级原因
- [ ] `runtime_startup_degraded` 事件记录启动时的降级原因

### 6.3 明确不会做的事

Phase 11 **不会**做以下事情：

- 外部遥测集成
- 专用指标端点
- 更丰富的每个子系统实时计数器或队列深度
- 除 `/health` 外的运维调试/状态端点
- 日志事件告警或持久化

---

## 7. 设计原则

### 7.1 增量扩展

Phase 11 的健康增强是**增量式**的：

- 不删除既有字段
- 不改变既有结构
- 新增字段放在合适位置

这确保了 `/health` 的 API 兼容性。

### 7.2 结构化优于文本

日志采用结构化格式（JSON），而非自由文本：

```python
# 好：结构化
logger.info("task_assigned", task_id="xxx", worker_id="yyy")

# 差：文本
logger.info(f"Task {task_id} assigned to worker {worker_id}")
```

结构化日志便于：

- 日志聚合系统解析
- 条件查询
- 指标提取

### 7.3 运维友好

健康信息和日志以**运维视角**设计：

- 包含足够的上下文（reason、counts）
- 不需要运维人员去理解代码细节
- 问题定位优先通过 health + 日志完成

### 7.4 事件名稳定性

Phase 11 定义的事件名应该**保持稳定**：

- 不频繁重命名
- 如需重命名，确保有兼容性理由

这让基于事件名的监控/告警系统更可靠。

---

## 8. Explicitly Not Done Yet

以下功能在 Phase 11 中**仍未完成**：

- [ ] 外部遥测集成（如 Datadog、Prometheus）
- [ ] 专用指标端点
- [ ] 更丰富的每个子系统实时计数器或队列深度
- [ ] 除 `/health` 外的运维调试/状态端点
- [ ] 日志事件告警或持久化

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-10-学习笔记]] — 运行时正确性与失败语义
- [[../phase_11_status.md|phase_11_status.md]] — Phase 11 给 Codex 的状态文档
