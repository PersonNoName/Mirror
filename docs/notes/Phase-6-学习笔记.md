# Phase 6 学习笔记：异步进化层

> **前置阶段**：[[Phase-5-学习笔记]]  
> **目标**：在前台对话链路和 Sub-Agent 异步执行链路之上，补齐“事件总线 → 观察 → 反思 → 认知更新 → 人格演化”的后台进化闭环  
> **里程碑**：本阶段完成后系统首次具备“从互动和任务结果中学习”的基础能力

---

## 目录

- [概述](#概述)
- [1. Phase 6 文件清单](#1-phase-6-文件清单)
- [2. 异步进化层总架构](#2-异步进化层总架构)
- [3. Redis Streams Event Bus](#3-redis-streams-event-bus)
- [4. 持久化 Outbox 与 Relay](#4-持久化-outbox-与-relay)
- [5. ObserverEngine](#5-observerengine)
- [6. MetaCognitionReflector](#6-metacognitionreflector)
- [7. CognitionUpdater 与 CoreMemoryScheduler](#7-cognitionupdater-与-corememoryscheduler)
- [8. PersonalityEvolver](#8-personalityevolver)
- [9. EvolutionJournal 与查询 API](#9-evolutionjournal-与查询-api)
- [10. 稳定性辅助层](#10-稳定性辅助层)
- [11. 启动流程](#11-启动流程)
- [12. 优雅降级策略](#12-优雅降级策略)
- [13. 验收标准](#13-验收标准)

---

## 概述

### 目标

Phase 6 的目标是**把系统的“学习”从同步主链路里拆出去**，改成后台异步处理。

前台只负责：
- 接收用户消息
- 生成回复或派发任务
- 产出事件

后台进化层负责：
- 从对话中抽取信号和知识
- 从任务结果中生成经验教训
- 更新 Core Memory 和人格规则
- 记录进化日志

### 完整闭环

```text
前台对话 / 异步任务完成
    ↓
EventBus.emit(...)
    ↓
OutboxStore（PostgreSQL 持久化）
    ↓
OutboxRelay → Redis Streams
    ↓
Observer / Reflector / 其他消费者
    ↓
CognitionUpdater / PersonalityEvolver / CoreMemoryScheduler
    ↓
Core Memory / Graph / Vector / Journal 更新
```

### 本阶段解决的核心问题

- Phase 4/5 已经能“运行”，但还不会“学习”
- 前台逻辑不能直接承担复杂抽取和压缩，否则会拖慢用户响应
- 学习过程要可降级，不能因为 Redis、PostgreSQL 或模型异常把主链路拖死
- Core Memory 的写入必须统一收口，避免多处并发写导致快照混乱

---

## 1. Phase 6 文件清单

| 文件 | 内容 |
|------|------|
| `app/evolution/event_bus.py` | Redis Streams 事件总线、事件数据模型 |
| `app/infra/outbox_store.py` | PostgreSQL 持久化 outbox |
| `app/tasks/outbox_relay.py` | 从持久化 outbox 向 Redis Streams 投递 |
| `app/evolution/signal_extractor.py` | 规则式交互信号抽取 |
| `app/evolution/observer.py` | 对话观察器，抽取三元组 |
| `app/evolution/reflector.py` | 任务反思器，生成 Lesson |
| `app/evolution/cognition_updater.py` | 将 Lesson 写回自我认知 / 世界模型 |
| `app/evolution/core_memory_scheduler.py` | Core Memory 串行写入与预算控制 |
| `app/evolution/personality_evolver.py` | 快速适应和慢速人格演化 |
| `app/evolution/evolution_journal.py` | 进化日志持久化 |
| `app/evolution/scheduler.py` | 夜间维护调度壳 |
| `app/stability/*.py` | circuit breaker / idempotency / snapshot |
| `app/api/journal.py` | `GET /evolution/journal` |
| `app/main.py` | Phase 6 组件装配与订阅注册 |
| `migrations/004_phase6_evolution.sql` | Phase 6 数据库迁移 |

---

## 2. 异步进化层总架构

### 2.1 事件类型

```python
class EventType:
    DIALOGUE_ENDED = "dialogue_ended"
    OBSERVATION_DONE = "observation_done"
    LESSON_GENERATED = "lesson_generated"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_WAITING_HITL = "task_waiting_hitl"
    HITL_FEEDBACK = "hitl_feedback"
    EVOLUTION_DONE = "evolution_done"
```

这些事件把“前台行为”和“后台学习”解耦开：

- `DIALOGUE_ENDED`：对话结束，驱动观察和快速适应
- `TASK_COMPLETED` / `TASK_FAILED`：任务产出结果，驱动反思
- `LESSON_GENERATED`：反思已经形成 lesson，驱动认知更新
- `OBSERVATION_DONE` / `EVOLUTION_DONE`：标识后台阶段完成

### 2.2 三条核心进化支线

```text
1. Dialogue 支线
dialogue_ended
  ├─> SignalExtractor -> PersonalityEvolver.fast_adapt()
  └─> ObserverEngine -> observation_done

2. Task 支线
task_completed / task_failed
  └─> MetaCognitionReflector -> lesson_generated

3. Cognition 支线
lesson_generated
  └─> CognitionUpdater -> CoreMemoryScheduler.write(...)
```

### 2.3 关键原则

- 前台只发事件，不直接做重抽取、重压缩、重写入
- 所有 Core Memory 更新都收口到 `CoreMemoryScheduler`
- 事件先写 durable outbox，再投递 Redis Streams
- 消费端默认支持 pending 恢复和幂等保护
- 模型不可用时后台静默跳过，不阻塞前台

---

## 3. Redis Streams Event Bus

### 3.1 流拆分

Phase 6 没有把所有事件都塞进一个总 stream，而是按意图拆流：

```python
EVENT_STREAMS = {
    EventType.DIALOGUE_ENDED: "stream:event:dialogue",
    EventType.OBSERVATION_DONE: "stream:event:evolution",
    EventType.LESSON_GENERATED: "stream:event:evolution",
    EventType.TASK_COMPLETED: "stream:event:task_result",
    EventType.TASK_FAILED: "stream:event:task_result",
    EventType.TASK_WAITING_HITL: "stream:event:task_result",
    EventType.HITL_FEEDBACK: "stream:event:dialogue",
    EventType.EVOLUTION_DONE: "stream:event:evolution",
}
```

这样做的意义：

- 对话事件和任务事件分开，消费延迟不互相污染
- 进化类事件单独成流，便于后续扩展更多消费者
- 可根据类型设置不同 consumer group 和重试策略

### 3.2 Event 数据模型

```python
@dataclass(slots=True)
class Event:
    type: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid4()))
    priority: int = 1
    stream_name: str = ""
    delivery_id: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)
```

这里的重点不是复杂，而是足够统一：

- `id` 用于幂等
- `stream_name` / `delivery_id` 用于消费确认
- `payload` 保持开放结构，方便前后台传输

### 3.3 RedisStreamsEventBus 工作方式

```python
async def emit(self, event: Event) -> None:
    event.stream_name = self.stream_for_type(event.type)
    await self.outbox_store.enqueue(
        self.outbox_store.from_payload(event.stream_name, {"event": self._serialize_event(event)})
    )
```

这里最关键的一点是：

- `emit()` 不直接 `xadd`
- 而是先写 `OutboxStore`

这保证了“事件已产生”与“稍后一定会投递”之间有一个 durable 缓冲层。

### 3.4 消费模型

```python
async def start(self) -> None:
    if self.degraded:
        return
    ...
    await self.redis_client.xgroup_create(...)
    self._tasks.append(asyncio.create_task(self._consume(...)))
```

消费端沿用 Phase 5 的 Redis Streams 模式：

- `XGROUP CREATE`
- `XREADGROUP` 读新消息
- `XAUTOCLAIM` 恢复 pending
- 成功后 `XACK`

如果配置了 `IdempotencyStore`，同一个事件还会先 `claim(scope, event.id)` 再执行 handler。

---

## 4. 持久化 Outbox 与 Relay

### 4.1 为什么要从内存 outbox 升级

Phase 5 的 outbox 还是以内存为主，适合跑通链路，但不够稳。

Phase 6 把事件传输升级为：

```text
业务组件 emit
    ↓
OutboxStore.enqueue()    # PostgreSQL
    ↓
OutboxRelay.list_pending()
    ↓
Redis XADD
    ↓
mark_published() / schedule_retry()
```

### 4.2 OutboxStore 的职责

`app/infra/outbox_store.py` 负责：

- 写入 `outbox_events`
- 查询 pending 事件
- 标记已发布
- 记录重试退避时间
- PostgreSQL 不可用时降级到内存镜像

```python
async def list_pending(self, limit: int = 100) -> list[OutboxEvent]:
    ...
    SELECT ...
    FROM outbox_events
    WHERE status = 'pending'
      AND (next_retry_at IS NULL OR next_retry_at <= NOW())
```

这让 EventBus 和真正的 Redis 投递解耦了：

- 生产事件的人只管 `enqueue`
- 发送失败可以独立重试
- 就算 Redis 短暂不可用，事件也不会直接丢

### 4.3 Relay 在 Phase 6 的角色

`OutboxRelay` 不再只是 Task 派发工具，而是整个系统事件 transport 的发布器。

这意味着：

- 任务派发和进化事件共享同一套 durable outbox 机制
- 事件流语义比 Phase 5 更统一

---

## 5. ObserverEngine

### 5.1 职责

`ObserverEngine` 负责**把对话转成 durable knowledge**。

输入：
- `DIALOGUE_ENDED`

输出：
- 写入 Graph
- 写入 Vector
- emit `OBSERVATION_DONE`

### 5.2 批处理策略

```python
class ObserverEngine:
    BATCH_WINDOW_SECONDS = 30
    MAX_BATCH_SIZE = 5
```

行为是：

- 同一个 `user_id` 的对话事件先缓冲
- 满 5 条立即 flush
- 否则 30 秒后延迟 flush

这是一种很典型的“前台轻、后台批处理”设计：

- 避免每轮对话都立即调模型
- 降低 Qdrant / Neo4j 写放大
- 给后续抽取留更多上下文

### 5.3 三元组抽取

```python
payload = [
    {
        "role": "system",
        "content": (
            "从对话中抽取 JSON 数组三元组。关系仅允许 "
            "PREFERS / DISLIKES / USES / KNOWS / HAS_CONSTRAINT / IS_GOOD_AT / IS_WEAK_AT。"
        ),
    },
    {"role": "user", "content": dialogue},
]
```

抽取结果会做两步处理：

1. `extract_json()` 解析模型返回
2. `_align_triple()` 做轻量实体对齐

当前对齐还很轻，只是小字典别名修正，例如：

- `pyhton` -> `Python`
- `vsc` / `vscode` -> `VSCode`

### 5.4 写入目标

```python
if self.graph_store is not None:
    await self.graph_store.upsert_relation(...)

if self.vector_retriever is not None:
    await self.vector_retriever.upsert(...)
```

写入分工：

- Neo4j 存关系真相
- Qdrant 存语义片段

最后再发：

```python
await self.event_bus.emit(Event(type=EventType.OBSERVATION_DONE, payload={...}))
```

这保证“观察完成”本身也是系统事件，而不是隐藏副作用。

---

## 6. MetaCognitionReflector

### 6.1 职责

`MetaCognitionReflector` 负责**从任务成败里总结 Lesson**。

输入：
- `TASK_COMPLETED`
- `TASK_FAILED`

输出：
- `LESSON_GENERATED`

### 6.2 触发方式

```python
async def handle_task_completed(self, event: Event) -> None:
    await self._reflect(event, "done")

async def handle_task_failed(self, event: Event) -> None:
    await self._reflect(event, "failed")
```

反思器会先从 `TaskStore` 回查任务快照，再构造 prompt。

### 6.3 Lesson 生成

```python
return Lesson(
    source_task_id=task.id,
    user_id=task.metadata.get("user_id", ""),
    domain=task.metadata.get("domain", task.assigned_to or "general"),
    outcome=outcome,
    category="reflection",
    summary=data.get("lesson", ""),
    root_cause=data.get("root_cause", ""),
    ...
)
```

Lesson 不只是“一句总结”，还包含：

- `root_cause`
- `domain`
- `is_agent_capability_issue`
- `subject / relation / object`
- `confidence`

这些字段后面直接决定更新哪一块认知。

### 6.4 为什么要加阈值

```python
if lesson is None or lesson.confidence < 0.5:
    return
```

这一步很关键：

- 不是所有任务结果都值得写回系统认知
- 低置信 lesson 宁可丢掉，也不要污染长期记忆

---

## 7. CognitionUpdater 与 CoreMemoryScheduler

### 7.1 CognitionUpdater 的职责

`CognitionUpdater` 负责把 `Lesson` 落到正确的认知块里。

```python
if lesson.is_agent_capability_issue:
    await self._update_self_cognition(lesson)
else:
    await self._update_world_model(lesson)
```

它本身不直接随意写 Core Memory，而是委托给 `CoreMemoryScheduler`。

### 7.2 Self Cognition 更新

如果 lesson 指向“代理能力问题”，就更新：

- `capability_map`
- `known_limits`

```python
if lesson.outcome == "done":
    entry.confidence = min(1.0, entry.confidence + 0.05)
else:
    entry.confidence = max(0.0, entry.confidence - 0.1)
```

这体现了一种非常朴素但合理的学习逻辑：

- 成功 -> 增加能力置信度
- 失败 -> 降低置信度并补充限制

### 7.3 World Model 更新

如果 lesson 更像外部世界知识，就：

- 先写图关系
- 再要求 `CoreMemoryScheduler` 重建 `world_model`

```python
await self.core_memory_scheduler.write(lesson.user_id, "world_model", None, event_id=lesson.id)
```

这里传 `None` 不是空写，而是触发内部 `rebuild_world_model_snapshot()`。

### 7.4 CoreMemoryScheduler：唯一写入口

这是 Phase 6 最重要的约束之一。

```python
async def write(self, user_id: str, block: str, content: Any, event_id: str | None = None) -> CoreMemory:
    async with self._locks[user_id]:
        current = deepcopy(await self.core_memory_cache.get(user_id))
        ...
        await self.core_memory_store.save_snapshot(user_id, current, version)
        await self.core_memory_cache.set(user_id, current, version=version)
```

它解决的问题：

- 同一用户的 Core Memory 写入串行化
- 防止多个后台组件同时改快照
- 写前可统一做预算控制和压缩

### 7.5 Token 预算控制

```python
BLOCK_BUDGETS = {
    "self_cognition": 1000,
    "world_model": 1000,
    "personality": 800,
    "task_experience": 1200,
}
TOTAL_TOKEN_BUDGET = 5000
```

如果某块超预算，会先尝试模型压缩：

```python
"压缩以下 {block_name} JSON，保留核心事实与 pinned 项，返回 JSON。"
```

压缩失败则走本地截断：

- 保留 pinned 项
- 只留最近少量非 pinned 项
- 映射类结构只保留前几个 key

这避免 Core Memory 无上限膨胀。

---

## 8. PersonalityEvolver

### 8.1 双路径设计

`PersonalityEvolver` 不是一次性改整个人格，而是分成：

- `fast_adapt()`：会话级快速适应
- `slow_evolve()`：长期规则晋升

### 8.2 快速适应

`SignalExtractor` 先用规则从对话中抓轻量信号：

```python
if any(token in text for token in ("简洁一点", "简短", "少点", "别太长", "concise", "shorter")):
    signal_type = "prefer_concise"
elif any(token in text for token in ("中文", "说中文", "请用中文", "chinese")):
    signal_type = "language_zh"
elif any(token in text for token in ("少点客套", "直接一点", "不要太客气")):
    signal_type = "tone_direct"
```

然后交给：

```python
await self.personality_evolver.fast_adapt(signal)
```

`fast_adapt()` 会把 adaptation 写进 `SessionContextStore`，所以它只影响当前 session prompt 组装，不会立刻污染长期人格。

### 8.3 慢速演化

当同类信号累计达到阈值：

```python
SIGNAL_CONFIRMATION = 3
```

系统会触发：

```python
await self.slow_evolve(signal.user_id)
```

慢速演化会：

1. 保存旧人格快照
2. 把高频 adaptation 晋升为 `behavioral_rules`
3. 检查 drift
4. 重生成 `baseline_description`
5. 通过 `CoreMemoryScheduler.write()` 落盘

### 8.4 漂移保护

```python
@staticmethod
def _detect_drift(personality: Any) -> bool:
    return len(personality.behavioral_rules) > 10
```

如果规则太多，系统会回滚到最新 snapshot，而不是继续把人格越改越散。

这是一个很粗糙但很实用的 V1 防御措施。

---

## 9. EvolutionJournal 与查询 API

### 9.1 为什么需要 Journal

进化如果只改状态、不留轨迹，后面很难排查：

- 为什么这个用户的人格规则变了
- 某次快适应是怎么触发的
- 哪次 slow evolve 进行了规则晋升

所以 Phase 6 增加了 append-only journal。

### 9.2 数据结构

```python
@dataclass(slots=True)
class EvolutionEntry:
    id: str = field(default_factory=lambda: str(uuid4()))
    user_id: str = ""
    event_type: str = ""
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
```

### 9.3 Journal 的记录点

当前已经记录的典型事件包括：

- `fast_adaptation`
- `rule_promoted`
- `baseline_shifted`

未来也可以继续往里加更多 evolution audit 信息。

### 9.4 API

```python
@router.get("/evolution/journal")
async def evolution_journal(...):
    items = await request.app.state.evolution_journal.list_recent(...)
```

返回结构里包含：

- `id`
- `user_id`
- `event_type`
- `summary`
- `details`
- `created_at`

这让前端或调试脚本能直接查看系统最近学到了什么。

---

## 10. 稳定性辅助层

### 10.1 AsyncCircuitBreaker

Phase 6 首次给后台模型调用加了一个统一的异步熔断器。

```python
failure_rate_threshold = 0.5
time_window_seconds = 60
open_duration_seconds = 30
minimum_calls = 3
```

它现在主要保护：

- `ObserverEngine` 的 `lite.extraction`
- `MetaCognitionReflector` 的 `lite.extraction`
- `CoreMemoryScheduler` 的压缩调用

这样在模型持续报错时，不会每条事件都继续猛打外部依赖。

### 10.2 IdempotencyStore

消费事件前先抢占幂等 key：

```python
claimed = await self.idempotency_store.claim(scope, event.id)
if not claimed:
    await self.redis_client.xack(...)
    return
```

这避免 Redis pending 恢复或重复投递时，一个事件被重复处理多次。

### 10.3 PersonalitySnapshotStore

人格快照目前还是内存版：

- 每个用户保留最近若干快照
- 用于 slow evolve 漂移回滚

当前还不是 durable persistence，所以进程重启后会丢。

---

## 11. 启动流程

### 11.1 `main.py` 装配顺序

Phase 6 的生命周期装配已经明显比前几期复杂：

```python
# 1. 初始化持久层
task_store = TaskStore()
outbox_store = OutboxStore()
idempotency_store = IdempotencyStore()
evolution_journal = EvolutionJournal()

# 2. 初始化 Redis / Memory / Model
redis_client = Redis.from_url(...)
core_memory_store = CoreMemoryStore()
core_memory_cache = CoreMemoryCache(...)
session_context_store = SessionContextStore(...) or _NullSessionContextStore()
model_registry = ModelProviderRegistry(...)

# 3. 初始化 EventBus 与任务系统
event_bus = RedisStreamsEventBus(...)
task_system = TaskSystem(..., outbox_store=outbox_store, redis_client=redis_client)
outbox_relay = OutboxRelay(outbox_store=outbox_store, redis_client=redis_client)

# 4. 初始化进化组件
core_memory_scheduler = CoreMemoryScheduler(...)
personality_evolver = PersonalityEvolver(...)
signal_extractor = SignalExtractor(...)
observer = ObserverEngine(...)
reflector = MetaCognitionReflector(...)
cognition_updater = CognitionUpdater(...)
scheduler = EvolutionScheduler(...)

# 5. 注册订阅
await event_bus.subscribe("dialogue_ended", observer.handle_dialogue_ended)
await event_bus.subscribe("dialogue_ended", signal_extractor.handle_dialogue_ended)
await event_bus.subscribe("task_completed", reflector.handle_task_completed)
await event_bus.subscribe("task_failed", reflector.handle_task_failed)
await event_bus.subscribe("lesson_generated", cognition_updater.handle_lesson_generated)

# 6. 启动后台组件
outbox_relay.start()
task_monitor.start()
worker_manager.start()
await event_bus.start()
scheduler.start()
```

### 11.2 新的系统形态

从这里能看出，Mirror 到 Phase 6 已经不只是：

- 一个 FastAPI 应用
- 一个同步聊天接口

而是开始具备：

- 前台同步链路
- 后台任务执行链路
- 后台事件驱动学习链路

这三套 runtime 并存的形态。

---

## 12. 优雅降级策略

### 12.1 降级矩阵

| 组件不可用 | 降级行为 |
|-----------|---------|
| Redis 不可用 | EventBus degraded，进化消费者不运行，但前台仍可启动 |
| PostgreSQL 不可用 | Outbox / Journal / Idempotency 回退到内存或 no-op |
| lite.extraction 不可用 | Observer / Reflector / 压缩静默跳过 |
| Neo4j 不可用 | `graph_store = None`，世界模型图关系不写入 |
| Qdrant 不可用 | `vector_retriever = None`，向量写入跳过 |

### 12.2 关键理解

这套降级策略的重点不是“功能完全等价”，而是：

- 主链路优先活着
- 学习链路能跑就跑，跑不了就降级
- 不允许后台演化反过来拖垮前台

这也是 Phase 6 最重要的工程取舍。

---

## 13. 验收标准

### 13.1 验收命令

```bash
python -m compileall app

python -c "from app.main import app; print(app.title)"

curl http://127.0.0.1:8000/evolution/journal
```

### 13.2 验收检查项

- [ ] `RedisStreamsEventBus` 能完成订阅、消费、ack、pending 恢复
- [ ] `emit()` 事件会先进入 `OutboxStore`
- [ ] `OutboxRelay` 能将 pending 事件投递到 Redis Streams
- [ ] `ObserverEngine` 能从 `dialogue_ended` 批量抽取三元组
- [ ] `MetaCognitionReflector` 能从任务成败生成 `Lesson`
- [ ] `CognitionUpdater` 只能通过 `CoreMemoryScheduler` 更新长期记忆
- [ ] `PersonalityEvolver.fast_adapt()` 能写入 session adaptations
- [ ] `GET /evolution/journal` 能返回最近进化记录
- [ ] Redis / PostgreSQL / lite model 不可用时，前台仍能启动

---

## 附：Explicitly Not Done Yet

以下功能在 Phase 6 中**仍未完成**：

- [ ] 更强的世界模型综合，而不只是当前的 relation summary
- [ ] 真正可用的夜间调度策略组合
- [ ] 进程重启后仍然保留的人格快照持久化
- [ ] 更复杂的实体合并、别名治理和知识冲突处理

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-4-学习笔记]] — 前台推理链路
- [[Phase-5-学习笔记]] — Sub-Agent 异步执行
- [[../phase_6_status.md|phase_6_status.md]] — Phase 6 给 Codex 的状态文档
