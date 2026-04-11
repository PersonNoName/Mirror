# Phase 15 学习笔记：集成与端到端置信度

> **前置阶段**：[[Phase-14-学习笔记]]  
> **目标**：建立本地集成测试切片，将真实运行时子系统连接起来验证端到端链路  
> **里程碑**：本阶段完成后系统具备本地集成测试能力，覆盖同步 chat、异步任务派发、HITL 响应循环和降级路径

---

## 目录

- [概述](#概述)
- [1. Phase 15 文件清单](#1-phase-15-文件清单)
- [2. 为什么需要集成测试](#2-为什么需要集成测试)
- [3. 集成测试切片设计](#3-集成测试切片设计)
- [4. 覆盖的端到端路径](#4-覆盖的端到端路径)
- [5. 子系统连接方式](#5-子系统连接方式)
- [6. 持久化边缘处理](#6-持久化边缘处理)
- [7. 验证与验收](#7-验证与验收)
- [8. 设计原则](#8-设计原则)
- [9. Explicitly Not Done Yet](#9-explicitly-not-done-yet)
- [10. Phase 15 的意义](#10-phase-15-的意义)

---

## 概述

### 目标

Phase 15 的目标是**建立端到端集成测试**，验证真实运行时子系统连接后的行为。

Phase 14 清理了 API 契约，Phase 15 则验证这些契约在真实子系统交互中是否正确工作。

### Phase 14 到 Phase 15 的演进

Phase 14 之后，每个子系统（SoulEngine、ActionRouter、TaskSystem 等）都有单元测试：

- 单元测试：验证单个组件的正确性 ✓
- 集成测试：验证组件之间的交互 ✗

Phase 15 填补了这个空白。

### 新的系统形态

```
单元测试覆盖
    ↓
├─ SoulEngine.test_run()
├─ ActionRouter.test_route()
├─ TaskSystem.test_dispatch()
└─ ...
    ↓
集成测试覆盖
    ↓
test_soul_engine_plus_router_plus_platform()  ← Phase 15 新增
```

---

## 1. Phase 15 文件清单

| 文件 | 内容 |
|------|------|
| `tests/test_integration_runtime.py` | 本地集成测试切片 |

---

## 2. 为什么需要集成测试

### 2.1 单元测试的局限

单元测试只能验证**隔离的组件**：

```python
# 单元测试：测试 ActionRouter
def test_action_router_route():
    router = ActionRouter(...)
    result = router.route(action)
    assert result == expected
```

但单元测试**无法验证**：

- SoulEngine 生成的 action 是否能被 ActionRouter 正确路由
- TaskSystem 分发的任务是否能被 TaskWorker 正确处理
- HITL 响应是否能正确恢复任务

### 2.2 集成测试的价值

集成测试验证**子系统之间的交互**：

```python
# 集成测试：测试完整链路
async def test_chat_happy_path():
    # 真实子系统连接
    soul_engine = SoulEngine(...)
    action_router = ActionRouter(...)
    task_system = TaskSystem(...)
    platform_adapter = WebPlatformAdapter(...)

    # 端到端执行
    response = await chat_endpoint(
        user_id="user_1",
        message="Hello",
        ...
    )

    # 验证端到端行为
    assert response.reply is not None
    assert response.status == "completed"
```

### 2.3 本地优先策略

Phase 15 坚持**本地优先**策略：

- 不依赖 Redis、PostgreSQL、Neo4j、Qdrant
- 不依赖 OpenCode 服务器
- 外部依赖用 in-memory doubles 替代

这确保：

- 测试可以在任何环境快速运行
- 不需要配置外部服务
- 测试失败即发现真实问题

---

## 3. 集成测试切片设计

### 3.1 测试文件位置

```
tests/
    test_integration_runtime.py  ← Phase 15 新增
```

### 3.2 测试切片原则

Phase 15 的集成测试是**切片式**的，不是全量启动：

- 不是启动整个 `bootstrap_runtime()`
- 而是选择性地连接需要验证的子系统
- 边界清晰的测试场景

### 3.3 测试场景

| 场景 | 说明 |
|------|------|
| 同步 `/chat` 快乐路径 | 推理 + 路由 + 平台分发 |
| 异步任务派发路径 | 任务创建 → Agent 选择 → 派发 → Worker 完成 → 出站通知 |
| HITL 响应循环 | chat → waiting_hitl → /hitl/respond → 任务恢复 → 反馈注册 |
| 降级路径 | Redis 不可用时的 safe reply 和 503 错误 |

---

## 4. 覆盖的端到端路径

### 4.1 同步 `/chat` 快乐路径

```
/chat 请求
    ↓
SoulEngine.run()  ← 真实推理
    ↓
ActionRouter.route()  ← 真实路由
    ↓
WebPlatformAdapter.fan_out()  ← 真实平台分发
    ↓
ChatResponse
```

验证点：

- 推理正确生成 reply
- 路由正确识别 action type
- 平台分发正确处理响应

### 4.2 异步任务派发路径

```
/chat 请求（触发异步任务）
    ↓
SoulEngine.run()
    ↓
ActionRouter.route() → action_type=task_dispatch
    ↓
TaskSystem.create_task()  ← 真实任务创建
    ↓
Agent selection
    ↓
TaskWorker 模拟完成
    ↓
Async outbound completion message
```

验证点：

- 任务正确创建
- Agent 正确选择
- 派发正确发布
- Worker 正确完成
- 完成消息正确发送

### 4.3 HITL 响应循环

```
/chat 请求（触发 HITL）
    ↓
SoulEngine.run()
    ↓
ActionRouter.route() → action_type=hitl_relay
    ↓
TaskSystem.waiting_hitl()
    ↓
/hitl/respond
    ↓
TaskSystem.resume_task()
    ↓
HITL feedback registration
    ↓
任务继续执行
```

验证点：

- HITL 状态正确保存
- 响应正确恢复任务
- 反馈正确注册

### 4.4 降级路径

```
/chat 请求（Redis 不可用）
    ↓
SoulEngine.run()
    ↓
ActionRouter.route()
    ↓
WebPlatformAdapter.fan_out()
    ↓
检测到 streaming_disabled=True
    ↓
ChatResponse.reply = safe_reply
    ↓
status = "completed"（降级下仍返回 safe reply）
```

```
/chat/stream 请求（Redis 不可用）
    ↓
检测到 streaming_disabled=True
    ↓
503 ErrorEnvelope(code="STREAMING_UNAVAILABLE", ...)
```

验证点：

- `/chat` 在降级时仍返回 safe reply
- `/chat/stream` 在降级时返回结构化 503 错误

---

## 5. 子系统连接方式

### 5.1 真实子系统对象

Phase 15 使用**真实的子系统对象**进行集成测试：

```python
# 真实 SoulEngine
soul_engine = SoulEngine(
    model_registry=model_registry,
    tool_registry=tool_registry,
    hook_registry=hook_registry,
    ...
)

# 真实 ActionRouter
action_router = ActionRouter(
    tool_registry=tool_registry,
    agent_registry=agent_registry,
    event_bus=event_bus,
    ...
)

# 真实 TaskSystem
task_system = TaskSystem(
    task_store=in_memory_task_store,  # 内存替代持久化
    outbox_store=in_memory_outbox_store,
    ...
)
```

### 5.2 真实调用链

Phase 15 的集成测试**真实调用**子系统方法：

```python
async def test_sync_chat_path():
    # 不是 mock，而是真实调用
    action = await soul_engine.run(user_message)
    
    result = await action_router.route(action)
    
    response = await web_platform.fan_out(result)
    
    assert response.reply is not None
```

### 5.3 Worker 路径处理

TaskWorker 的集成测试有意调用：

```python
# 直接调用 _handle_message，避免需要真实 Redis Streams
await task_worker._handle_message(test_message)
```

这避免了依赖真实 Redis Streams，同时仍然验证了：

- 任务 finalize 行为
- 失败通知行为

---

## 6. 持久化边缘处理

### 6.1 外部依赖替换策略

Phase 15 用 in-memory doubles 替换持久化边缘：

| 外部依赖 | 替代方案 |
|---------|---------|
| Redis | In-memory double（内存字典） |
| PostgreSQL | In-memory task store |
| Neo4j | Skip 或 mock |
| Qdrant | Skip 或 mock |
| OpenCode | Skip 或 mock |

### 6.2 In-Memory TaskStore 示例

```python
class InMemoryTaskStore:
    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._events: list[Event] = []

    async def save(self, task: Task) -> None:
        self._tasks[task.id] = task

    async def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    async def list_pending(self, limit: int = 100) -> list[Task]:
        return [t for t in self._tasks.values() if t.status == "pending"]
```

### 6.3 边缘不渗透原则

Phase 15 确保**持久化边缘不渗透到集成测试内部**：

- 集成测试只验证业务逻辑
- 持久化问题由单独的存储测试覆盖
- 集成测试失败不会因为持久化边缘不完整而误报

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

- [ ] 66 个测试全部通过（Phase 14 的 62 + Phase 15 新增）
- [ ] `test_integration_runtime.py` 存在且覆盖关键路径
- [ ] 同步 `/chat` 快乐路径测试通过
- [ ] 异步任务派发路径测试通过
- [ ] HITL 响应循环测试通过
- [ ] 降级路径测试通过
- [ ] 测试不依赖真实 Redis
- [ ] 测试不依赖真实 PostgreSQL
- [ ] 测试不依赖真实 Neo4j/Qdrant
- [ ] 测试不依赖真实 OpenCode

### 7.3 明确不会做的事

Phase 15 **不会**做以下事情：

- 外部服务支撑的集成测试套件
- 可选的 dockerized 集成环境
- 带所有真实依赖的完整 `bootstrap_runtime()` 启动到请求的端到端测试
- 生产部署验证
- 浏览器/客户端级别的端到端测试

---

## 8. 设计原则

### 8.1 本地优先

集成测试**本地优先**，不依赖外部服务：

- 任何开发者 clone 代码后可以立即运行
- CI 可以在没有服务依赖的情况下运行
- 测试失败指向真实问题，不是配置问题

### 8.2 切片式覆盖

集成测试是**切片式**的，不是全量启动：

- 选择关键路径验证
- 边界清晰
- 失败时容易定位问题子系统

### 8.3 真实调用

集成测试使用**真实子系统调用**，不是过度 mock：

- 验证真实的交互协议
- 发现 mock 不会发现的交互问题
- 确保组件之间的接口匹配

### 8.4 边缘隔离

持久化边缘用 in-memory doubles 隔离：

- 不污染集成测试
- 不需要配置外部服务
- 专注于业务逻辑验证

---

## 9. Explicitly Not Done Yet

以下功能在 Phase 15 中**仍未完成**：

- [ ] 外部服务支撑的集成测试套件
- [ ] 可选的 dockerized 集成环境
- [ ] 带所有真实依赖的完整 `bootstrap_runtime()` 端到端测试
- [ ] 生产部署验证
- [ ] 浏览器/客户端级别的端到端测试

---

## 10. Phase 15 的意义

### 10.1 完成当前优化计划

Phase 15 是当前 `OPTIMIZATION_PLAN.md` 序列的**终点**：

```
Phase 0-7:  核心框架搭建
Phase 8:    文本完整性
Phase 9:    测试基础设施
Phase 10:   失败语义
Phase 11:   可观测性
Phase 12:   WebAgent 真实搜索
Phase 13:   检索与记忆质量
Phase 14:   API 清理
Phase 15:   集成与端到端置信度
```

### 10.2 从"能跑"到"能验证"

Phase 15 完成后，系统从"能跑"升级到"能验证"：

- 每个 Phase 的功能有测试覆盖
- 关键路径有集成测试验证
- 降级路径有明确的测试保证

### 10.3 后续扩展基础

Phase 15 建立的集成测试切片是**后续扩展的基础**：

- 未来新增功能 → 扩展集成测试
- 未来修改运行时 → 验证集成测试仍然通过
- 未来架构调整 → 集成测试作为回归网

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-14-学习笔记]] — API 与产品表面清理
- [[../phase_15_status.md|phase_15_status.md]] — Phase 15 给 Codex 的状态文档
