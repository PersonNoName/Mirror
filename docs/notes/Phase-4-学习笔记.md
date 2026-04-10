# Phase 4 学习笔记：前台推理链路

> **前置阶段**：[[Phase-3-学习笔记]]  
> **目标**：打通"用户发消息 → 推理 → 动作路由 → 响应"完整同步链路  
> **里程碑**：本阶段完成后系统首次可以对话

---

## 目录

- [概述](#概述)
- [1. 完整同步链路架构](#1-完整同步链路架构)
- [2. Soul Engine](#2-soul-engine)
- [3. ActionRouter](#3-actionrouter)
- [4. Task 系统](#4-task-系统)
- [5. Blackboard](#5-blackboard)
- [6. Agent 注册表](#6-agent-注册表)
- [7. OutboxRelay](#7-outboxrelay)
- [8. TaskMonitor](#8-taskmonitor)
- [9. WebPlatformAdapter](#9-webplatformadapter)
- [10. API 路由](#10-api-路由)
- [11. 启动流程](#11-启动流程)
- [12. 优雅降级策略](#12-优雅降级策略)
- [13. 验收标准](#13-验收标准)

---

## 概述

### 目标

Phase 4 的目标是**打通前台同步链路**，使系统首次可以对话。

```
用户消息
    ↓
POST /chat → SoulEngine.run() → ActionRouter.route()
    ↓
┌─────────────────────────────────────────────┐
│  Action.type = "direct_reply"               │
│    → WebPlatformAdapter.send_outbound()    │
│    → EventBus.emit(DIALOGUE_ENDED)          │
└─────────────────────────────────────────────┘
或
┌─────────────────────────────────────────────┐
│  Action.type = "publish_task"               │
│    → Blackboard.evaluate_agents()           │
│    → Blackboard.assign() → TaskSystem       │
│    → HITL 或 异步派发                        │
└─────────────────────────────────────────────┘
```

### Phase 4 文件清单

| 文件 | 内容 |
|------|------|
| `app/soul/engine.py` | SoulEngine（组装 Prompt + 调用模型 + 解析 Action） |
| `app/soul/router.py` | ActionRouter（四种动作路由） |
| `app/soul/models.py` | Action 数据类 |
| `app/tasks/task_system.py` | TaskSystem（任务创建和派发门面） |
| `app/tasks/store.py` | TaskStore（PostgreSQL + 内存降级） |
| `app/tasks/blackboard.py` | Blackboard（任务分配和生命周期） |
| `app/tasks/outbox_relay.py` | OutboxRelay（Outbox → Redis Streams） |
| `app/tasks/monitor.py` | TaskMonitor（心跳超时检测） |
| `app/tasks/models.py` | Task/TaskResult/Lesson 数据类 |
| `app/platform/web.py` | WebPlatformAdapter（SSE + HTTP） |
| `app/api/chat.py` | `/chat` 和 `/chat/stream` 路由 |
| `app/api/hitl.py` | `/hitl/respond` 路由 |
| `app/agents/registry.py` | AgentRegistry |
| `app/evolution/runtime_bus.py` | InMemoryEventBus |
| `app/main.py` | 启动流程编排 |
| `migrations/003_phase4_tasks.sql` | tasks 表 schema |

---

## 1. 完整同步链路架构

### 1.1 消息流

```
POST /chat
    ↓
chat.py::chat()
    ↓
WebPlatformAdapter.normalize_inbound()  → InboundMessage
    ↓
SessionContextStore.append_message()     → 保存用户消息
    ↓
SoulEngine.run()                        → Action
    ↓
ActionRouter.route()                    → 路由到不同处理分支
    ↓
┌────────────────────────────────────────────┐
│ direct_reply:                              │
│   → PlatformAdapter.send_outbound()       │
│   → EventBus.emit(DIALOGUE_ENDED)         │
│   → SessionContextStore.append_message()   │ 保存助手回复
└────────────────────────────────────────────┘
```

### 1.2 四种 Action 类型

```python
ActionType = Literal["direct_reply", "tool_call", "publish_task", "hitl_relay"]
```

| Action | 含义 | 处理 |
|--------|------|------|
| `direct_reply` | 直接回复用户 | `send_outbound()` + `emit(DIALOGUE_ENDED)` |
| `tool_call` | 调用工具 | Phase 4 回退为 `direct_reply` |
| `publish_task` | 发布任务 | `Blackboard.assign()` → 派发给 SubAgent |
| `hitl_relay` | 等待人工介入 | `send_hitl()` 发送 HITL 请求 |

---

## 2. Soul Engine

### 2.1 职责

- 组装 System Prompt（记忆 + 规则 + Session 上下文）
- 调用 `reasoning.main` 模型
- 解析模型输出为结构化 `Action`
- 无 API Key 时回退为本地直答

### 2.2 System Prompt 组装顺序

```python
SOUL_SYSTEM_PROMPT_TEMPLATE = """
## 你的自我认知
{self_cognition}

## 你对世界的理解
{world_model}

## 你的人格基调
{baseline_description}

## 你从交互中学到的行为规则（必须遵守）
{behavioral_rules}

## 本次对话适应（仅当前 Session 有效）
{session_adaptations}

## 你积累的经验
{task_experience}

## 工具列表
{tool_list}

## 行为约束
- 禁止使用讨好性词汇
- 若认为用户请求不合理，必须在 inner_thoughts 中记录异议
- 先思考，再行动：任何动作前必须生成 <inner_thoughts>

## 输出格式
<inner_thoughts>[你的内部独白]</inner_thoughts>
<action>[one of: direct_reply | tool_call | publish_task | hitl_relay]</action>
<content>[对应动作的内容]</content>
"""
```

### 2.3 SoulEngine.run() 流程

```python
async def run(self, message: InboundMessage) -> Action:
    # 1. 获取 Core Memory
    core_memory = await self.core_memory_cache.get(message.user_id)
    
    # 2. 获取最近 Session 消息
    recent_messages = await self._get_recent_messages(message)
    
    # 3. 向量检索上下文
    retrieved = await self._retrieve_context(message)
    
    # 4. 组装 Prompt
    prompt = self._build_prompt(core_memory, recent_messages, retrieved)
    
    # 5. 检查 API Key
    if not api_key:
        return self._fallback_action(message)
    
    # 6. 调用模型
    response = await self.model_registry.chat("reasoning.main").generate(messages)
    
    # 7. 解析 Action
    parsed = self._parse_action(raw_text)
    if parsed is None:
        return self._fallback_action(message, raw_response=raw_text)
    
    return parsed
```

### 2.4 Action 解析

```python
@staticmethod
def _parse_action(raw_text: str) -> Action | None:
    # 解析 <inner_thoughts>...</inner_thoughts>
    inner_match = re.search(r"<inner_thoughts>\s*(.*?)\s*</inner_thoughts>", raw_text, re.S)
    # 解析 <action>...</action>
    action_match = re.search(r"<action>\s*(.*?)\s*</action>", raw_text, re.S)
    # 解析 <content>...</content>
    content_match = re.search(r"<content>\s*(.*?)\s*</content>", raw_text, re.S)
    
    if not action_match or not content_match:
        return None  # 解析失败，回退
    
    action_type = action_match.group(1).strip()
    if action_type not in {"direct_reply", "tool_call", "publish_task", "hitl_relay"}:
        return None  # 非法类型，回退
    
    return Action(
        type=action_type,
        content=content_match.group(1).strip(),
        inner_thoughts=inner_match.group(1).strip() if inner_match else "",
    )
```

### 2.5 回退策略

```python
@staticmethod
def _fallback_action(message: InboundMessage, raw_response: str = "") -> Action:
    reply = (
        "我是 Mirror 的主代理，目前运行在本地降级模式。"
        f"你刚刚说的是：{message.text}"
    )
    return Action(
        type="direct_reply",
        content=reply,
        inner_thoughts="模型不可用，使用本地回退直答。",
        raw_response=raw_response,
    )
```

---

## 3. ActionRouter

### 3.1 职责

路由四种 Action 类型到不同处理模块。

### 3.2 direct_reply 分支

```python
if action.type == "direct_reply":
    await platform_adapter.send_outbound(
        ctx,
        OutboundMessage(type="text", content=str(action.content)),
    )
    await event_bus.emit(
        Event(
            type=EventType.DIALOGUE_ENDED,
            payload={...},
        )
    )
```

### 3.3 publish_task 分支（任务派发）

```python
if action.type == "publish_task":
    # 1. 创建任务
    task = await task_system.create_task_from_action(action, inbound_message)
    
    # 2. 评估 Agent
    best_agent, cap_score = await blackboard.evaluate_agents(task)
    
    # 3. 置信度 < 0.3 → 升级 HITL
    if not best_agent or cap_score < 0.3:
        request = HitlRequest(task_id=task.id, title="需要用户确认", description=...)
        await blackboard.on_task_waiting_hitl(task, request)
        await platform_adapter.send_hitl(ctx, request)
        return {...}
    
    # 4. task.assigned_to 必须在 assign() 之前赋值
    task.assigned_to = best_agent.name
    
    # 5. 置信度 0.3~0.5 → 执行但告知用户
    if cap_score < 0.5:
        await blackboard.assign(task)
        message = f"正在尝试处理，但置信度偏低（{cap_score:.2f}），结果可能需要你确认。"
        await platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=message))
        return {...}
    
    # 6. 置信度 > 0.5 → 静默执行
    await blackboard.assign(task)
    message = "任务已派发，等待异步处理。"
    await platform_adapter.send_outbound(ctx, OutboundMessage(type="text", content=message))
    return {...}
```

### 3.4 关键约束

- `task.assigned_to` **必须在** `blackboard.assign()` 之前赋值
- `direct_reply` 结束时 **必须** `emit(DIALOGUE_ENDED)` 事件

---

## 4. Task 系统

### 4.1 TaskSystem

```python
class TaskSystem:
    DISPATCH_STREAM = "stream:task:dispatch"
    RETRY_STREAM = "stream:task:retry"
    DLQ_STREAM = "stream:task:dlq"
    
    async def create_task_from_action(self, action: Action, inbound_message: InboundMessage) -> Task:
        # 1. 创建 Task
        task = Task(intent=str(action.content), prompt_snapshot=inbound_message.text, ...)
        
        # 2. 写入 TaskStore（PostgreSQL 或内存）
        await self.task_store.create(task)
        
        # 3. 创建 OutboxEvent
        event = OutboxEvent(topic=self.DISPATCH_STREAM, payload={"task": asdict(task)})
        self.outbox_events[event.id] = event
        
        return task
```

### 4.2 Redis Streams 派发

```python
async def publish_dispatch(self, task: Task) -> None:
    if self.redis_client is None:
        return
    await self.redis_client.xadd(
        self.DISPATCH_STREAM,
        {"task_id": task.id, "assigned_to": task.assigned_to, "intent": task.intent},
    )
```

### 4.3 Task 数据类

```python
@dataclass(slots=True)
class Task:
    id: str = field(default_factory=lambda: str(uuid4()))
    parent_task_id: str | None = None
    assigned_to: str = ""              # 必须在 assign() 前赋值
    intent: str = ""
    prompt_snapshot: str = ""
    status: TaskStatus = "pending"
    priority: int = 1
    result: dict[str, Any] | None = None
    error_trace: str | None = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    last_heartbeat_at: datetime = field(default_factory=utc_now)
    heartbeat_timeout: int = 30
    dispatch_stream: str = "stream:task:dispatch"
    consumer_group: str = "main-agent"
    delivery_token: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 4.4 TaskStatus

```python
TaskStatus = Literal[
    "pending",      # 等待调度
    "running",      # 执行中
    "waiting_hitl",  # 等待人工介入
    "done",         # 已完成
    "failed",       # 失败
    "interrupted",  # 中断
    "cancelled",    # 取消
]
```

---

## 5. Blackboard

### 5.1 职责

无状态协调器，通过 TaskStore 持久化，通过 EventBus 通知。

### 5.2 核心方法

```python
class Blackboard:
    async def evaluate_agents(self, task: Task) -> tuple[Any | None, float]:
        # 遍历所有注册 Agent，评分返回最高
        best_agent, best_score = None, 0.0
        for agent in self.agent_registry.all():
            score = await agent.estimate_capability(task)
            if score > best_score:
                best_agent, best_score = score
        return best_agent, best_score
    
    async def assign(self, task: Task) -> None:
        task.status = "running"
        await self.task_store.update(task)
        await self.task_system.publish_dispatch(task)  # 投递到 Redis Streams
    
    async def on_task_waiting_hitl(self, task: Task, request: Any) -> None:
        task.status = "waiting_hitl"
        task.metadata["hitl_request"] = {...}
        await self.task_store.update(task)
        await self.event_bus.emit(Event(type=EventType.TASK_WAITING_HITL, ...))
    
    async def resume(self, task_id: str, hitl_result: dict[str, Any]) -> Task | None:
        # 恢复被挂起的任务
        task = await self.task_store.get(task_id)
        task.metadata["hitl_result"] = hitl_result
        task.status = "running"
        await self.task_store.update(task)
        return task
    
    async def on_task_complete(self, task: Task, result: dict[str, Any] | None = None) -> None:
        task.status = "done"
        task.result = result
        await self.task_store.update(task)
        await self.event_bus.emit(Event(type=EventType.TASK_COMPLETED, ...))
    
    async def on_task_failed(self, task: Task, error: str) -> None:
        task.status = "failed"
        task.error_trace = error
        await self.task_store.update(task)
        await self.event_bus.emit(Event(type=EventType.TASK_FAILED, ...))
    
    async def terminate_agent(self, agent_name: str) -> None:
        agent = self.agent_registry.get(agent_name)
        if agent:
            await agent.cancel()
```

---

## 6. Agent 注册表

### 6.1 AgentRegistry

```python
class AgentRegistry:
    """In-memory registry for sub-agent instances."""
    
    def __init__(self) -> None:
        self._agents: dict[str, SubAgent] = {}
    
    def register(self, agent: SubAgent) -> None:
        self._agents[agent.name] = agent
    
    def get(self, name: str) -> SubAgent | None:
        return self._agents.get(name)
    
    def all(self) -> list[SubAgent]:
        return list(self._agents.values())

agent_registry = AgentRegistry()  # 全局单例
```

### 6.2 关键设计

- Blackboard **只通过** `AgentRegistry` 查找 Agent
- **不能**直接 import 具体 Agent 类
- Phase 5 会注册 CodeAgent 和 WebAgent

---

## 7. OutboxRelay

### 7.1 职责

轮询 `TaskSystem.outbox_events`，投递到 Redis Streams。

### 7.2 实现

```python
class OutboxRelay:
    def __init__(self, task_system: Any, redis_client: Any | None = None, interval_seconds: float = 1.0) -> None:
        self.task_system = task_system
        self.redis_client = redis_client
        self.interval_seconds = interval_seconds
        self.degraded = redis_client is None  # Redis 不可用时降级
    
    async def _run(self) -> None:
        while True:
            for event in list(self.task_system.outbox_events.values()):
                if event.status == "published":
                    continue
                if self.redis_client is not None:
                    await self.redis_client.xadd(event.topic, {"payload": str(event.payload), "event_id": event.id})
                event.status = "published"
                event.published_at = event.created_at
            await asyncio.sleep(self.interval_seconds)
```

### 7.3 降级行为

- Redis 不可用时 → `degraded = True`，不执行投递
- Phase 4 任务派发实际不依赖 Redis Streams 消费者

---

## 8. TaskMonitor

### 8.1 职责

定期扫描心跳超时的任务，标记为失败。

### 8.2 实现

```python
class TaskMonitor:
    async def _run(self) -> None:
        while True:
            now = datetime.now(timezone.utc)
            for task in await self.task_store.get_by_status("running"):
                if (now - task.last_heartbeat_at).total_seconds() > task.heartbeat_timeout:
                    await self.blackboard.on_task_failed(task, "Agent Heartbeat Lost")
            await asyncio.sleep(self.interval_seconds)  # 默认 10 秒
```

---

## 9. WebPlatformAdapter

### 9.1 职责

- 实现 `PlatformAdapter` 接口
- 支持 SSE 流式和普通 HTTP 响应
- 内存内 SSE 广播（多订阅者支持）

### 9.2 订阅机制

```python
class WebPlatformAdapter(PlatformAdapter):
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = defaultdict(list)
    
    def subscribe(self, session_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[session_id].append(queue)
        return queue
    
    def unsubscribe(self, session_id: str, queue: asyncio.Queue) -> None:
        listeners = self._queues.get(session_id, [])
        if queue in listeners:
            listeners.remove(queue)
        if not listeners:
            self._queues.pop(session_id, None)
```

### 9.3 SSE 广播

```python
async def send_outbound(self, ctx: PlatformContext, message: OutboundMessage) -> None:
    if "streaming" in ctx.capabilities:
        # 流式：分块发送 delta
        for chunk in self._chunk_text(str(message.content)):
            await self._broadcast(ctx.session_id, {"event": "delta", "data": {"delta": chunk}})
    
    # 完整消息
    await self._broadcast(ctx.session_id, {"event": "message", "data": payload})
    
    # 结束信号
    await self._broadcast(ctx.session_id, {"event": "done", "data": {"status": "done"}})
```

---

## 10. API 路由

### 10.1 POST /chat（同步对话）

```python
@router.post("/chat")
async def chat(request: Request, payload: ChatRequest) -> dict[str, Any]:
    # 1. 规范化入站消息
    inbound = await app_state.web_platform.normalize_inbound({...})
    
    # 2. 保存用户消息到 Session 上下文
    await app_state.session_context_store.append_message(inbound.user_id, inbound.session_id, {"role": "user", "content": inbound.text})
    
    # 3. Soul Engine 推理
    action = await app_state.soul_engine.run(inbound)
    
    # 4. Action 路由
    result = await app_state.action_router.route(action, inbound)
    
    # 5. 保存助手回复到 Session 上下文
    await app_state.session_context_store.append_message(inbound.user_id, inbound.session_id, {"role": "assistant", "content": result["reply"]})
    
    return result
```

### 10.2 GET /chat/stream（SSE 流式）

```python
@router.get("/chat/stream")
async def chat_stream(request: Request, session_id: str) -> StreamingResponse:
    # 1. 订阅 SSE
    queue = app_state.web_platform.subscribe(session_id)
    
    async def event_generator():
        try:
            while True:
                item = await queue.get()
                yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
                if item["event"] == "done":
                    break
        finally:
            app_state.web_platform.unsubscribe(session_id, queue)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

### 10.3 POST /hitl/respond（HITL 响应）

```python
@router.post("/hitl/respond")
async def hitl_respond(request: Request, payload: HitlResponseRequest) -> dict[str, Any]:
    task = await request.app.state.blackboard.resume(
        payload.task_id,
        {"decision": payload.decision, "payload": payload.payload},
    )
    await request.app.state.task_system.register_hitl_response(
        payload.task_id, payload.decision, payload.payload,
    )
    return {"status": "ok", "task_id": payload.task_id, "decision": payload.decision}
```

---

## 11. 启动流程

### 11.1 main.py lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 初始化 TaskStore（PostgreSQL → 降级内存）
    task_store = TaskStore()
    await task_store.initialize()
    
    # 2. 初始化 Redis 客户端（不可用时为 None）
    redis_client = await Redis.from_url(settings.redis.url)  # 失败 → None
    
    # 3. 初始化 Core Memory
    core_memory_store = CoreMemoryStore()
    core_memory_cache = CoreMemoryCache(store=core_memory_store, redis_client=redis_client)
    
    # 4. 初始化 Session Context（Redis → 降级 NullStore）
    session_context_store = SessionContextStore(redis_client) if redis_client else _NullSessionContextStore()
    
    # 5. 初始化 Model Registry
    model_registry = ModelProviderRegistry(build_routing_from_settings(settings))
    
    # 6. 初始化平台适配器
    web_platform = WebPlatformAdapter()
    event_bus = InMemoryEventBus()
    
    # 7. 初始化 Task 系统
    task_system = TaskSystem(task_store=task_store, redis_client=redis_client)
    blackboard = Blackboard(task_store=task_store, task_system=task_system, agent_registry=agent_registry, event_bus=event_bus)
    outbox_relay = OutboxRelay(task_system=task_system, redis_client=redis_client)
    task_monitor = TaskMonitor(task_store=task_store, blackboard=blackboard)
    
    # 8. 初始化 Vector Retriever（不可用时为 None）
    vector_retriever = VectorRetriever(model_registry=model_registry, core_memory_cache=core_memory_cache)
    
    # 9. 初始化 Soul Engine 和 ActionRouter
    soul_engine = SoulEngine(model_registry=model_registry, core_memory_cache=core_memory_cache, ...)
    action_router = ActionRouter(platform_adapter=web_platform, event_bus=event_bus, blackboard=blackboard, task_system=task_system)
    
    # 10. 绑定到 app.state
    app.state.xxx = xxx
    
    # 11. 启动后台任务
    outbox_relay.start()
    task_monitor.start()
    
    yield
    
    # shutdown
    await outbox_relay.stop()
    await task_monitor.stop()
    await redis_client.aclose()
```

---

## 12. 优雅降级策略

### 12.1 降级矩阵

| 组件不可用 | 降级行为 |
|-----------|---------|
| 无 API Key | `SoulEngine` 回退为本地 `direct_reply` |
| PostgreSQL 不可用 | `TaskStore` 降级为内存模式 |
| Redis 不可用 | `SessionContextStore` → `_NullSessionStore`，`OutboxRelay` → no-op |
| Qdrant 不可用 | `VectorRetriever` → 返回空 matches |
| 模型输出格式错误 | `Action` 回退为 `direct_reply` |

### 12.2 关键原则

- **不因单点故障导致完全不可用**
- 降级时记录 `logger.warning`
- 后续 Phase 可逐步强化各组件

---

## 13. 验收标准

### 13.1 验收命令

```bash
uvicorn app.main:app --port 8000

# 同步对话
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"text": "你好，介绍一下你自己", "session_id": "s001"}'
# 期望：返回 AI 回复

# SSE 流式
curl -N 'http://localhost:8000/chat/stream?session_id=s002'
# 另开终端发消息，期望 SSE 持续输出 delta 后以 done 结束
```

### 13.2 验收检查项

- [ ] `POST /chat` 返回 AI 回复
- [ ] 无 API Key 时返回降级回复
- [ ] `/chat/stream` 支持 SSE 流式
- [ ] `ActionRouter` 正确路由四种 Action
- [ ] `Blackboard.evaluate_agents()` 可用
- [ ] `OutboxRelay` 和 `TaskMonitor` 后台运行

---

## 附：Explicitly Not Done Yet

以下功能在 Phase 4 中**未实现**：

- [ ] 真正的工具执行（`tool_call` 回退为 `direct_reply`）
- [ ] Sub-agent Worker 从 Redis Streams 消费任务
- [ ] 进程重启后的持久化任务恢复
- [ ] 有效 API Key 下的模型结构化输出验证

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-0-学习笔记]] — Phase 0 学习笔记
- [[Phase-1-学习笔记]] — Phase 1 学习笔记
- [[Phase-2-学习笔记]] — Phase 2 学习笔记
- [[Phase-3-学习笔记]] — Phase 3 学习笔记
- [[Phase-5-学习笔记|Phase 5]] — Sub-agent 实现（待完成）
