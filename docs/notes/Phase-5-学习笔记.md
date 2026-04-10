# Phase 5 学习笔记：Sub-Agent 执行

> **前置阶段**：[[Phase-4-学习笔记]]  
> **目标**：实现 Sub-Agent 异步执行运行时，打通 "任务派发 → Worker 消费 → Agent 执行" 完整链路  
> **里程碑**：本阶段完成后系统具备后台异步任务执行能力

---

## 目录

- [概述](#概述)
- [1. Phase 5 文件清单](#1-phase-5-文件清单)
- [2. Sub-Agent 架构](#2-sub-agent-架构)
- [3. CodeAgent](#3-codeagent)
- [4. WebAgent](#4-webagent)
- [5. Redis Streams 任务派发](#5-redis-streams-任务派发)
- [6. TaskWorker](#6-taskworker)
- [7. TaskWorkerManager](#7-taskworkerManager)
- [8. HITL 权限处理](#8-hitl-权限处理)
- [9. 启动流程](#9-启动流程)
- [10. 优雅降级策略](#10-优雅降级策略)
- [11. 验收标准](#11-验收标准)

---

## 概述

### 目标

Phase 5 的目标是**实现 Sub-Agent 异步执行运行时**，使系统可以将任务派发给后台 Worker 执行。

```
任务派发（TaskSystem.publish_dispatch）
    ↓
OutboxRelay 写入 Redis Streams
    ↓
TaskWorker 消费（XREADGROUP）
    ↓
CodeAgent / WebAgent 执行
    ↓
结果通知 SSE 订阅者
```

### 核心实现

- `CodeAgent`：对接 OpenCode 的代码执行 Agent
- `WebAgent`：网页搜索 Agent 占位实现
- `TaskWorker`：Redis Streams 消费者，负责从对应 Stream 读取任务并调用 Agent 执行
- `TaskWorkerManager`：管理所有 Worker 的生命周期

---

## 1. Phase 5 文件清单

| 文件 | 内容 |
|------|------|
| `app/agents/code_agent.py` | CodeAgent（OpenCode 对接） |
| `app/agents/web_agent.py` | WebAgent（占位实现） |
| `app/agents/base.py` | SubAgent 抽象基类 |
| `app/agents/registry.py` | AgentRegistry（全局注册表） |
| `app/tasks/worker.py` | TaskWorker + TaskWorkerManager |
| `app/tasks/task_system.py` | 任务派发门面 + Stream/Group 命名工具 |
| `app/tasks/store.py` | TaskStore（PostgreSQL + 内存降级） |
| `app/main.py` | 启动流程：注册 Agent + 启动 Workers |

---

## 2. Sub-Agent 架构

### 2.1 SubAgent 抽象基类

```python
class SubAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def domain(self) -> str: ...

    @abstractmethod
    async def estimate_capability(self, task: Task) -> float:
        """评估 Agent 对任务的处理能力，返回 0.0~1.0 的置信度"""

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """执行任务，返回结果"""

    async def resume(self, task: Task, hitl_result: dict[str, Any]) -> TaskResult:
        """恢复被 HITL 挂起的任务（可选实现）"""

    async def cancel(self) -> None:
        """取消正在执行的任务（可选实现）"""
```

### 2.2 AgentRegistry

```python
class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}

    def register(self, agent: SubAgent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> SubAgent | None:
        return self._agents.get(name)

    def all(self) -> list[SubAgent]:
        return list(self._agents.values())

agent_registry = AgentRegistry()
```

### 2.3 Stream 和 Consumer Group 命名

每个 Agent 有独立的 Stream 和 Consumer Group：

| Stream | 用途 |
|--------|------|
| `stream:task:dispatch:<agent>` | 新任务派发 |
| `stream:task:retry:<agent>` | 重试任务 |
| `stream:task:dlq:<agent>` | 死信队列 |

Consumer Group：`group:<agent_name>`

```python
TaskSystem.stream_for_agent("code_agent", "stream:task:dispatch")
# → "stream:task:dispatch:code_agent"

TaskSystem.group_for_agent("code_agent")
# → "group:code_agent"
```

---

## 3. CodeAgent

### 3.1 职责

对接 OpenCode 平台，将内部任务请求转化为 OpenCode Session 调用。

### 3.2 能力评估

```python
async def estimate_capability(self, task: Task) -> float:
    text = f"{task.intent}\n{task.prompt_snapshot}".lower()
    score = 0.0
    # 高置信度关键词
    high = ["代码", "编程", "实现", "脚本", "debug", "调试", "重构", "python", "函数", "类", "run"]
    for keyword in high:
        if keyword in text:
            score += 0.18
    # 中置信度关键词
    medium = ["文件", "测试", "命令", "终端", "repo", "git"]
    for keyword in medium:
        if keyword in text:
            score += 0.08
    # 负向关键词
    negative = ["搜索网页", "联网", "浏览器", "图像生成"]
    for keyword in negative:
        if keyword in text:
            score -= 0.18
    return max(0.0, min(1.0, score if score > 0 else 0.05))
```

### 3.3 执行流程

```python
async def execute(self, task: Task) -> TaskResult:
    async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
        # 1. 创建 OpenCode Session
        session_id = await self._create_session(client, task)
        task.metadata["opencode_session_id"] = session_id
        await self.task_store.update(task)
        try:
            # 2. 发送 Prompt
            prompt = self._build_prompt(task)
            await client.post(
                f"/session/{session_id}/prompt_async",
                json={
                    "parts": [{"type": "text", "text": prompt}],
                    "format": {"type": "json_schema", "schema": TASK_RESULT_SCHEMA},
                },
            )
            # 3. 监听事件直到完成
            return await self._listen_until_done(client, session_id, task)
        finally:
            if task.status != "waiting_hitl":
                await self._safe_delete_session(client, session_id)
```

### 3.4 HITL 权限处理

```python
HIGH_RISK_PERMISSIONS = {"network_request", "dangerous_shell", "delete_files"}

async def _handle_permission(self, client, session_id, task, event) -> str:
    permission_type = event.get("permissionType", "").lower()

    # 低风险权限 → 自动批准
    if permission_type not in self.HIGH_RISK_PERMISSIONS:
        await client.post(f"/session/{session_id}/permissions/{permission_id}", json={"response": "approve"})
        return "approve"

    # 高风险权限 → 升级 HITL
    request = HitlRequest(
        task_id=task.id,
        title="需要权限确认",
        description=f"任务请求高风险权限：{permission_type}",
        risk_level="high",
        metadata={...},
    )
    await self.blackboard.on_task_waiting_hitl(task, request)
    response = await self.task_system.wait_for_hitl_response(task.id)
    decision = response.get("decision", "reject")

    # 向 OpenCode 反馈用户决策
    await client.post(
        f"/session/{session_id}/permissions/{permission_id}",
        json={"response": "approve" if decision == "approve" else "reject"},
    )
    task.status = "running"
    await self.task_store.update(task)
    return decision
```

### 3.5 结果获取

```python
async def _fetch_result(self, client, session_id, task) -> TaskResult:
    messages = (await client.get(f"/session/{session_id}/message")).json()

    for message in reversed(messages):
        info = message.get("info", {})
        if info.get("role") == "assistant":
            structured = info.get("structured_output")
            if structured and structured.get("success"):
                return TaskResult(
                    task_id=task.id,
                    status="done",
                    output={"summary": structured["summary"], "files_changed": structured.get("files_changed", [])},
                    metadata={"error_type": "NONE"},
                )
    # 解析失败
    return TaskResult(task_id=task.id, status="failed", error="no structured output", metadata={"error_type": "RETRYABLE"})
```

---

## 4. WebAgent

### 4.1 职责

网页搜索 Agent 占位实现，V1 阶段不执行真实联网抓取。

### 4.2 能力评估

```python
async def estimate_capability(self, task: Task) -> float:
    text = f"{task.intent}\n{task.prompt_snapshot}".lower()
    score = 0.0
    keywords = ["搜索", "查找", "资料", "文档", "说明", "网页", "网站", "检索"]
    negatives = ["代码", "脚本", "实现", "重构", "debug", "调试"]
    for keyword in keywords:
        if keyword in text:
            score += 0.16
    for keyword in negatives:
        if keyword in text:
            score -= 0.12
    return max(0.0, min(0.55, score))
```

### 4.3 执行

```python
async def execute(self, task: Task) -> TaskResult:
    return TaskResult(
        task_id=task.id,
        status="done",
        output={"summary": "WebAgent V1 占位闭环", "intent": task.intent, "mode": "placeholder"},
        metadata={"error_type": "NONE"},
    )
```

---

## 5. Redis Streams 任务派发

### 5.1 Stream 命名

```python
class TaskSystem:
    DISPATCH_STREAM = "stream:task:dispatch"
    RETRY_STREAM = "stream:task:retry"
    DLQ_STREAM = "stream:task:dlq"

    @classmethod
    def stream_for_agent(cls, agent_name: str, base_stream: str | None = None) -> str:
        stream = base_stream or cls.DISPATCH_STREAM
        return f"{stream}:{agent_name}"

    @staticmethod
    def group_for_agent(agent_name: str) -> str:
        return f"group:{agent_name}"
```

### 5.2 任务派发

```python
async def publish_dispatch(self, task: Task) -> None:
    event = OutboxEvent(topic=task.dispatch_stream, payload={"task": asdict(task)})
    self.outbox_events[event.id] = event

async def publish_retry(self, task: Task) -> None:
    event = OutboxEvent(
        topic=self.stream_for_agent(task.assigned_to, self.RETRY_STREAM),
        payload={"task": asdict(task)},
    )
    self.outbox_events[event.id] = event

async def publish_dlq(self, task: Task, error: str) -> None:
    event = OutboxEvent(
        topic=self.stream_for_agent(task.assigned_to, self.DLQ_STREAM),
        payload={"task": asdict(task), "error": error},
    )
    self.outbox_events[event.id] = event
```

### 5.3 Consumer Group 创建

```python
async def ensure_worker_groups(self, agent_name: str) -> None:
    await self.ensure_consumer_group(agent_name, self.DISPATCH_STREAM)
    await self.ensure_consumer_group(agent_name, self.RETRY_STREAM)
    await self.ensure_consumer_group(agent_name, self.DLQ_STREAM)

async def ensure_consumer_group(self, agent_name: str, stream_kind: str = DISPATCH_STREAM) -> None:
    stream = self.stream_for_agent(agent_name, stream_kind)
    group = self.group_for_agent(agent_name)
    try:
        await self.redis_client.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise
```

---

## 6. TaskWorker

### 6.1 职责

消费 Agent 专属的 Redis Streams，执行分配的任务。

### 6.2 初始化

```python
class TaskWorker:
    def __init__(self, *, agent, task_store, task_system, blackboard, platform_adapter=None, poll_block_ms=5000, pending_idle_ms=30_000):
        self.agent = agent
        self.task_store = task_store
        self.task_system = task_system
        self.blackboard = blackboard
        self.platform_adapter = platform_adapter
        self.poll_block_ms = poll_block_ms
        self.pending_idle_ms = pending_idle_ms
        self.redis_client = task_system.redis_client

        # 订阅 Agent 专属的 dispatch 和 retry stream
        self.streams = {
            task_system.stream_for_agent(agent.name, task_system.DISPATCH_STREAM): ">",
            task_system.stream_for_agent(agent.name, task_system.RETRY_STREAM): ">",
        }
        self.group = task_system.group_for_agent(agent.name)
        self.consumer = f"{agent.name}-worker"
        self.degraded = self.redis_client is None
```

### 6.3 主循环

```python
async def _run(self) -> None:
    await self.task_system.ensure_worker_groups(self.agent.name)
    while True:
        # 1. 恢复超时的 pending 消息
        await self._recover_pending()
        # 2. 阻塞读取新消息
        entries = await self.redis_client.xreadgroup(
            groupname=self.group,
            consumername=self.consumer,
            streams=self.streams,
            count=10,
            block=self.poll_block_ms,
        )
        for stream_name, messages in entries:
            for message_id, fields in messages:
                await self._handle_message(stream_name, message_id, fields)
```

### 6.4 Pending 消息恢复

```python
async def _recover_pending(self) -> None:
    for stream_name in self.streams:
        try:
            _, claimed, _ = await self.redis_client.xautoclaim(
                name=stream_name,
                groupname=self.group,
                consumername=self.consumer,
                min_idle_time=self.pending_idle_ms,
                start_id="0-0",
                count=10,
            )
        except Exception:
            continue
        for message_id, fields in claimed:
            await self._handle_message(stream_name, message_id, fields)
```

### 6.5 消息处理

```python
async def _handle_message(self, stream_name, message_id, fields) -> None:
    task_id = self._decode(fields.get("task_id"))
    if not task_id:
        await self.redis_client.xack(stream_name, self.group, message_id)
        return

    task = await self.task_store.get(task_id)
    if task is None:
        await self.redis_client.xack(stream_name, self.group, message_id)
        return

    task.delivery_token = str(message_id)
    task.consumer_group = self.group
    await self.task_store.update(task)

    try:
        result = await self.agent.execute(task)
        await self._finalize(task, result)
        await self.redis_client.xack(stream_name, self.group, message_id)
    except Exception as exc:
        await self._handle_failure(task, f"RETRYABLE: {exc}")
        await self.redis_client.xack(stream_name, self.group, message_id)
```

### 6.6 失败处理与重试

```python
async def _handle_failure(self, task, error, error_type=None) -> None:
    normalized = (error_type or "RETRYABLE").upper()
    # 可重试错误 → 发布到 retry stream
    if normalized == "RETRYABLE" and task.retry_count < task.max_retries:
        task.retry_count += 1
        task.status = "pending"
        await self.task_store.update(task)
        await self.task_system.publish_retry(task)
        return

    # 不可重试或已达最大重试 → 发布到 DLQ
    await self.blackboard.on_task_failed(task, error)
    await self.task_system.publish_dlq(task, error)
    await self._notify_failure(task, error)
```

### 6.7 结果通知

```python
async def _notify_session(self, task, output) -> None:
    if self.platform_adapter is None:
        return
    session_id = task.metadata.get("session_id")
    user_id = task.metadata.get("user_id") or session_id
    if not session_id:
        return
    ctx = PlatformContext(platform="web", user_id=user_id, session_id=session_id)
    await self.platform_adapter.send_outbound(
        ctx,
        OutboundMessage(type="text", content=output.get("summary") or "任务已完成。", metadata=output),
    )
```

---

## 7. TaskWorkerManager

### 7.1 职责

管理所有注册的 TaskWorker 的生命周期。

### 7.2 实现

```python
class TaskWorkerManager:
    def __init__(self, workers: list[TaskWorker]) -> None:
        self.workers = workers

    def start(self) -> None:
        for worker in self.workers:
            worker.start()

    async def stop(self) -> None:
        for worker in self.workers:
            await worker.stop()
```

---

## 8. HITL 权限处理

### 8.1 当前实现

Phase 5 的 HITL 实现特点：

- Worker 在 `wait_for_hitl_response()` 处**阻塞等待**
- 不释放 Worker 进程，任务状态保持 `waiting_hitl`
- 用户通过 `/hitl/respond` 提交决策
- TaskSystem 通过 Future 机制唤醒等待中的 Worker

### 8.2 局限性

- **进程重启后无法恢复**：当前 HITL 等待是内存中的 Future，进程重启后丢失
- 不支持远程会话持久化

### 8.3 HITL Future 机制

```python
class TaskSystem:
    def __init__(self, ...):
        self._hitl_waiters: dict[str, asyncio.Future[dict[str, Any]]] = {}

    async def wait_for_hitl_response(self, task_id: str, timeout_seconds: float | None = None) -> dict[str, Any]:
        existing = self.waiting_hitl.pop(task_id, None)
        if existing is not None:
            return existing
        future = asyncio.get_running_loop().create_future()
        self._hitl_waiters[task_id] = future
        try:
            return await asyncio.wait_for(future, timeout_seconds)
        finally:
            self._hitl_waiters.pop(task_id, None)

    async def register_hitl_response(self, task_id: str, decision: str, payload: dict[str, Any] | None = None) -> None:
        response = {"decision": decision, "payload": payload or {}}
        self.waiting_hitl[task_id] = response
        waiter = self._hitl_waiters.pop(task_id, None)
        if waiter is not None and not waiter.done():
            waiter.set_result(response)
```

---

## 9. 启动流程

### 9.1 main.py lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 初始化 TaskStore + Redis
    task_store = TaskStore()
    await task_store.initialize()
    redis_client = Redis.from_url(settings.redis.url)  # 失败 → None

    # 2. 初始化核心组件
    task_system = TaskSystem(task_store=task_store, redis_client=redis_client)
    blackboard = Blackboard(task_store=task_store, task_system=task_system, agent_registry=agent_registry, event_bus=event_bus)
    outbox_relay = OutboxRelay(task_system=task_system, redis_client=redis_client)
    task_monitor = TaskMonitor(task_store=task_store, blackboard=blackboard)

    # 3. 注册 Sub-Agent
    agent_registry.register(CodeAgent(task_store=task_store, blackboard=blackboard, task_system=task_system))
    agent_registry.register(WebAgent(task_store=task_store))

    # 4. 创建 Workers
    worker_manager = TaskWorkerManager([
        TaskWorker(
            agent=agent,
            task_store=task_store,
            task_system=task_system,
            blackboard=blackboard,
            platform_adapter=web_platform,
        )
        for agent in agent_registry.all()
    ])

    # 5. 启动后台任务
    outbox_relay.start()
    task_monitor.start()
    worker_manager.start()

    yield

    # 6. 关闭
    await worker_manager.stop()
    await outbox_relay.stop()
    await task_monitor.stop()
    await redis_client.aclose()
```

---

## 10. 优雅降级策略

### 10.1 降级矩阵

| 组件不可用 | 降级行为 |
|-----------|---------|
| Redis 不可用 | Worker Manager 空闲，任务保留在 Outbox 内存，OutboxRelay 不投递 |
| OpenCode 不可用 | CodeAgent 任务失败，进入重试/DLQ 流程 |
| PostgreSQL 不可用 | TaskStore 降级为内存模式（与 Phase 4 一致） |

### 10.2 Worker 降级

```python
class TaskWorker:
    def __init__(self, ...):
        self.degraded = self.redis_client is None

    def start(self) -> None:
        if self.degraded:
            return  # 不启动 Worker
        self._task = asyncio.create_task(self._run())
```

---

## 11. 验收标准

### 11.1 验收命令

```bash
# 编译检查
python -m compileall app

# 导入验证
python -c "from app.agents import CodeAgent, WebAgent; from app.tasks.worker import TaskWorker, TaskWorkerManager"
```

### 11.2 验收检查项

- [ ] `CodeAgent` 成功对接 OpenCode Session API
- [ ] `WebAgent` 占位实现返回固定结果
- [ ] Worker 正确订阅 `stream:task:dispatch:<agent>` 和 `stream:task:retry:<agent>`
- [ ] Worker 使用 `XREADGROUP` 消费新消息
- [ ] Worker 使用 `XAUTOCLAIM` 恢复超时的 pending 消息
- [ ] 低风险权限自动批准，高风险权限触发 HITL
- [ ] 任务完成后通过 SSE 通知订阅者
- [ ] 可重试错误进入重试流，不可重试错误进入 DLQ
- [ ] Redis 不可用时 Worker 不启动但主进程正常运行

---

## 附：Explicitly Not Done Yet

以下功能在 Phase 5 中**未实现**：

- [ ] 真实浏览器/网络 Agent 循环（`WebAgent` 为占位实现）
- [ ] 进程重启后 HITL 远程会话恢复
- [ ] Phase 6 进化管道和事件流持久化

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-0-学习笔记]] — Phase 0 学习笔记
- [[Phase-1-学习笔记]] — Phase 1 学习笔记
- [[Phase-2-学习笔记]] — Phase 2 学习笔记
- [[Phase-3-学习笔记]] — Phase 3 学习笔记
- [[Phase-4-学习笔记]] — Phase 4 学习笔记
- [[../docs/phase_5_status.md|phase_5_status.md]] — Phase 5 状态文档（给 Codex 看的）
