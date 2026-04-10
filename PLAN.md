# Harness Main Agent — PLAN.md（最终冻结版）

> **给 Codex 的说明**：本文档按阶段组织，每次只执行一个 Phase。阅读当前 Phase 即可开始编码，无需通读全文。实现细节由你自主决定，文档只规定任务边界、关键约束和验收标准。
>
> **架构参考**：`main_agent_architecture_v3.4.md`（同目录）。实现中遇到歧义时以架构文档为准。

---

## 项目背景

一个具备长期记忆和自我进化能力的个人 AI Agent。三层架构：

- **前台同步层**：接收用户消息 → 记忆检索 → LLM 推理 → 动作路由，目标响应 < 2s
- **任务执行层**：管理异步任务队列，调度 Sub-agent 执行，Blackboard 协调
- **后台进化层**：对话结束后异步触发，观察 → 反思 → 进化 → 更新记忆，永不阻塞前台

**运行环境**：Python 3.11+，asyncio 全链路，个人单用户本地部署。


## V1 范围与冻结边界（本版新增）

为避免 Codex 在实现后期过度展开，本版明确以下 **V1 必做** 与 **仅预留** 边界：

### V1 必做

- 打通前台同步链路：`PlatformAdapter -> Memory -> SoulEngine -> ActionRouter`
- 打通任务执行链路：`TaskSystem -> Redis Streams -> Blackboard -> CodeAgent`
- 落地 PostgreSQL / Neo4j / Qdrant / Redis 四类存储职责分层
- 落地 Redis Streams consumer group、pending recovery、DLQ 基础能力
- 落地 Core Memory 快照、缓存、失效广播最小闭环
- 落地后台异步观察、反思、认知更新、规则式人格更新的最小闭环
- 落地 Tool / Hook / Skill / MCP 的 **注册骨架**

### 本版仅预留，不作为 V1 完整交付目标

- **WebAgent 真正联网执行能力**：V1 仅做占位能力评分与最小闭环，不做复杂联网 agent loop
- **Skill / MCP 生态实现**：V1 只完成 registry、loader、manifest/配置读取，不做复杂协议兼容和生态管理
- **夜间调度器高级策略**：V1 只完成调度接口和基础压缩/清理入口，不要求完整策略库
- **多平台正式接入**：V1 只实现 WebPlatformAdapter
- **复杂多 worker 编排 / 分布式部署**：V1 保持单机单体，可为后续扩展预留接口

### 编码纪律

- 若某项能力被标记为“仅预留”，则只允许实现接口、注册入口、最小占位逻辑，不得为其扩展复杂业务分支
- 若实现中出现“可以继续做更多”的空间，优先补测试、幂等、回滚和日志，不扩展新功能面

---

## V1 基础设施选型（本版固定）

本版 PLAN 采用以下技术组合，并以此作为后续所有 Phase 的默认实现前提：

- **PostgreSQL**：系统主事实库，保存 sessions、tasks、task_events、core_memory_snapshots、evolution_journal、idempotency_keys 等
- **Neo4j**：长期稳定关系图谱，保存偏好、厌恶、能力判断、环境约束、工具使用偏好等稳定关系
- **Qdrant**：向量检索，保存情境经验、对话片段、反思结果和检索索引
- **Redis**：承担三类职责
  - **Redis Streams**：任务队列与后台事件总线
  - **Redis KV**：热缓存、会话临时状态、轻量锁
  - **Redis Pub/Sub**：仅用于 cache invalidation / SSE 辅助通知，不作为可靠消息主通道
- **OpenCode Server**：CodeAgent 的代码执行引擎
- **FastAPI + asyncio**：单体主服务与异步编排框架

### 固定设计原则

1. **PostgreSQL 是状态真相源**：任务状态、会话状态、Core Memory 快照、Journal 一律以 PostgreSQL 为准
2. **Redis 负责搬运，不负责最终真相**：Redis Streams 承载异步调度，但任务最终状态必须回写 PostgreSQL
3. **可靠投递优先使用 Outbox Pattern**：凡是“先写业务状态、再投递异步消息”的场景，统一采用 PostgreSQL `outbox_events` 表 + relay worker 投递 Redis Streams，避免双写不一致
4. **Neo4j 只写长期稳定关系**：不把任务运行态、队列状态、心跳等运行时数据写入图数据库
5. **Qdrant 只写语义检索数据**：不把规则真相和任务真相存入向量库
6. **可靠异步链路统一用 Redis Streams**：不要把 Redis Pub/Sub 用作主任务队列或可靠事件总线
7. **Core Memory 采用“PostgreSQL 快照 + 进程内缓存 + Redis 失效广播”**：避免直接把 Redis 当唯一持久化存储

---

## 关键解耦约束（所有 Phase 适用）

这是本项目最重要的架构原则，Codex 在每个 Phase 编码时均须遵守：

1. **模型调用**：所有 LLM / Embedding / Reranker 调用必须经过 `ModelProviderRegistry`，不得在业务代码中直接 import 任何厂商 SDK 或硬编码 `model=`、`api_key=`、`base_url=`
2. **平台收发**：所有用户消息的收发和 HITL 回写必须经过 `PlatformAdapter`，不得在推理或任务逻辑中直接操作 HTTP Response
3. **Agent 调度**：Blackboard 只通过 `AgentRegistry` 查找 Agent，不得直接 import 具体 Agent 类
4. **工具执行**：Soul Engine 的 tool_call 只通过 `ToolRegistry` 查找并执行
5. **Core Memory 写入**：所有进化组件写 Core Memory 必须经过 `CoreMemoryScheduler`，不得直接操作 PostgreSQL、Redis 或缓存对象
6. **事件通信**：进化组件只通过 `EventBus` 接收事件，不得直接调用前台模块
7. **消息消费确认**：任何基于 Redis Streams 的消费者，只有在 PostgreSQL 或目标存储写入成功后才允许 ACK
8. **Outbox 优先于直接双写**：业务事务与事件投递不得依赖“应用层先写数据库、再写 Redis”的非原子流程；必须通过 `outbox_events` + relay 保证最终投递
9. **缓存可失效，事实不可丢**：Redis 内任何键和值都视为可重建数据，关键状态必须可从 PostgreSQL / Neo4j / Qdrant 重建

---

## Phase 0 — 项目脚手架

**目标**：建立可运行的项目骨架，所有基础服务就绪。不写任何业务逻辑。

### 任务

**基础服务编排**：用 Docker Compose 启动五个本地服务——Qdrant（向量库）、Neo4j（图库）、Redis（Streams + KV + Pub/Sub）、PostgreSQL（关系型主库）、OpenCode（代码执行服务）。所有服务配置持久化卷和自动重启。

**项目结构**：建立完整的目录骨架和空模块文件（`__init__.py`），目录划分参考架构文档的模块列表。

**依赖声明**：`requirements.txt` 至少包含 `fastapi`、`uvicorn`、`httpx`、`httpx-sse`、`qdrant-client`、`redis`、`asyncpg`、`neo4j`、`pydantic-settings`、`structlog` 及版本约束。

**配置体系**：用 `pydantic-settings` 实现统一配置入口，从环境变量读取 PostgreSQL、Neo4j、Redis、Qdrant、OpenCode 与模型路由配置。提供 `.env.example` 模板，覆盖所有必要变量。

**应用入口**：FastAPI 应用，含 startup/shutdown 生命周期钩子（本阶段为空），以及 `GET /health` 端点。

**Outbox 基础表预留**：在 PostgreSQL migration 规划中预留 `outbox_events`、`stream_consumers`、`idempotency_keys` 等基础表，后续 Phase 4/6 直接使用。

### 验收

```bash
docker compose up -d && docker compose ps   # 所有服务 running
uvicorn app.main:app --port 8000            # 启动无报错
curl http://localhost:8000/health           # 返回 {"status": "ok"}
```

---

## Phase 1 — 解耦接口层

**目标**：定义全项目共用的数据结构和解耦边界的抽象接口（ABC）。本阶段只写接口，不写实现。

### 任务

**Platform 接口**（`app/platform/base.py`）：定义 `PlatformContext`、`InboundMessage`、`OutboundMessage`、`HitlRequest` 数据类，以及 `PlatformAdapter` 抽象基类（含 `normalize_inbound`、`send_outbound`、`send_hitl` 三个抽象方法）。

**Model Provider 接口**（`app/providers/base.py`）：定义 `ModelSpec` 数据类（含 profile、capability、provider_type、vendor、model、base_url 等字段），以及 `ChatModel`、`EmbeddingModel`、`RerankerModel` 三个抽象基类。

**SubAgent 接口**（`app/agents/base.py`）：定义 `SubAgent` 抽象基类，含 `execute`、`estimate_capability`（必须轻量，< 10ms，无网络调用）、`resume`、`cancel`、`emit_heartbeat` 方法。

**Task 数据结构**（`app/tasks/models.py`）：定义 `Task`（含完整状态机字段，status 包括 `waiting_hitl`）、`TaskResult`、`Lesson` 数据类。Task 需显式包含 `dispatch_stream`、`consumer_group`、`delivery_token` 等 Redis Streams 相关字段或 metadata 扩展位。

**Outbox 数据结构**（`app/tasks/outbox.py` 或 `app/infra/outbox.py`）：定义 `OutboxEvent` 数据类，至少包含 `id`、`topic`、`payload`、`status`、`retry_count`、`next_retry_at`、`created_at`、`published_at` 字段。

**Core Memory 数据结构**（`app/memory/core_memory.py`）：定义 `CoreMemory` 及其四个区块数据类（`SelfCognition`、`WorldModel`、`PersonalityState`、`TaskExperience`），以及 `BehavioralRule` 数据类。Core Memory 的持久化快照存储于 PostgreSQL，Redis 仅用于缓存和失效广播。

**Event 数据结构**（`app/evolution/event_bus.py`）：定义 `Event`、`InteractionSignal`、`EvolutionEntry` 数据类，以及 `EventType` 常量类（含 8 种事件类型，参考架构文档 §5.1）。Event 需携带 `priority`、`stream_name`、`delivery_id` 等字段，以适配 Redis Streams 实现。

**注册表骨架**：`ToolRegistry`（`app/tools/registry.py`）和 `HookRegistry`（`app/hooks/registry.py`）的接口定义，含全局单例。`HookPoint` 枚举包含 `PRE_REASON`、`POST_REASON`、`PRE_TASK`、`POST_REPLY` 四个插入点。Hook 执行时任何异常只记录日志，不中断主流程。

### 验收

```bash
python -c "
from app.platform.base import PlatformAdapter, InboundMessage
from app.providers.base import ModelSpec, ChatModel
from app.agents.base import SubAgent
from app.tasks.models import Task, Lesson
from app.memory.core_memory import CoreMemory
from app.evolution.event_bus import EventType
from app.tools.registry import tool_registry
from app.hooks.registry import HookRegistry, HookPoint
print('Phase 1 OK')
"
# 无 ImportError，无循环导入
```

---

## Phase 2 — Model Provider 实现

**目标**：实现 `ModelProviderRegistry` 和 `openai_compatible` 协议客户端，使全项目的模型调用可以正常工作。

### 任务

**`openai_compatible` 客户端**（`app/providers/openai_compat.py`）：实现 `ChatModel`（支持普通生成和流式 SSE）、`EmbeddingModel`（支持批量，自动分批处理）、`RerankerModel`（调用本地 reranker 服务）。全部使用 `httpx.AsyncClient`，不引入任何厂商 SDK。支持超时配置和指数退避重试。

**`ModelProviderRegistry`**（`app/providers/registry.py`）：按 profile 名称路由到对应实现实例，懒加载并缓存。提供从 `settings` 对象构建路由配置的工厂函数，涵盖 `reasoning.main`、`lite.extraction`、`retrieval.embedding`、`retrieval.reranker` 四个 profile。

### 关键约束

`provider_type` 表示协议族（`openai_compatible` / `ollama` / `native`），`vendor` 表示实际供应商，两者不绑定——同一个 `openai_compatible` 协议可以指向 OpenAI、MiniMax 或其他兼容服务，切换时只改配置，不改代码。

### 验收

```bash
python -c "
from app.config import settings
from app.providers.registry import ModelProviderRegistry, build_routing_from_settings
r = ModelProviderRegistry(build_routing_from_settings(settings))
print(type(r.chat('reasoning.main')))
print(type(r.embedding('retrieval.embedding')))
print('Phase 2 OK')
"
# 如有可用 API Key，进一步验证 generate() 和 embed() 返回正确格式
```

---

## Phase 3 — 记忆系统

**目标**：实现向量检索、图存储、Core Memory 持久化，使记忆的读写可以正常工作。

### 任务

**Vector 检索**（`app/memory/vector_retriever.py`）：实现两级检索流水线。Level 0 直接读 Core Memory 缓存；Level 2 做 Qdrant ANN 检索，召回 Top 20；当 Top 20 分数方差超过阈值时，按需触发 Reranker（Level 2.5），否则直接截取 Top 8。提供 `retrieve()` 和 `upsert()` 方法。Qdrant 用 payload filter 按 `user_id` 和 `namespace` 隔离数据。

**Graph 存储**（`app/memory/graph_store.py`）：封装 Neo4j，提供关系的读写接口（`upsert_relation`、`get_relation`、`query_relations_by_user`）以及生成图谱自然语言摘要的方法（供 Core Memory `world_model` 快照使用）。关系类型限定在架构文档 §5.2 定义的词表内。

**Core Memory 存储**（`app/memory/core_memory_store.py`）：实现 PostgreSQL 持久化，至少包含 `load_latest(user_id)`、`save_snapshot(user_id, core_memory, version)`、`list_snapshots(user_id)` 接口。最新快照作为真相源，支持历史版本回溯。

**Core Memory 缓存**（补充 `app/memory/core_memory.py`）：实现进程内 `CoreMemoryCache` 单例，常驻内存，per-user（同一用户所有 session 共享同一份）。进程启动时从 PostgreSQL 加载；写入后通过 Redis Pub/Sub 或版本号标记触发 `invalidate(user_id)`，下次推理自动获取最新版本。Redis 可选存放热副本，但不是唯一持久化位置。

**Session 上下文缓存**（`app/memory/session_context.py`）：用 Redis 保存当前 Session 最近若干轮原文和轻量适应状态，用于前台同步链路快速装配，不进入长期真相存储。

### 验收

```bash
python -c "
import asyncio
from app.memory.core_memory import CoreMemoryCache
from app.memory.core_memory_store import CoreMemoryStore

async def test():
    store = CoreMemoryStore(...)
    cache = CoreMemoryCache(store=store, redis_client=None)
    mem = await cache.get('test_user')
    print(mem.personality.baseline_description)
    print('Phase 3 OK')

asyncio.run(test())
"
# Vector 写入后检索，验证返回条目数量和格式
# Neo4j 中可查询到 upsert 的长期关系
```

---

## Phase 4 — 前台推理链路

**目标**：打通“用户发消息 → 推理 → 动作路由 → 响应”完整同步链路。本阶段完成后系统首次可以对话。

### 任务

**Soul Engine**（`app/soul/engine.py`）：组装 System Prompt（顺序：自我认知 → 世界观 → 人格基调 → 行为规则 → 本次适应 → 经验 → 工具列表 → 行为约束），附加检索到的记忆和当前 session 最近 5 轮原文，调用 `reasoning.main` 模型推理，解析输出为结构化 `Action`（含 `inner_thoughts`）。输出格式不稳定时回退为 `direct_reply`。

**ActionRouter**（`app/soul/router.py`）：路由四种动作类型。`publish_task` 分支中，先对所有 agent 评分，置信度 < 0.3 升级 HITL，0.3~0.5 之间执行但提前告知用户，> 0.5 静默执行。注意：`task.assigned_to` 必须在调用 `blackboard.assign()` 之前赋值。`direct_reply` 分支结束时 emit `DIALOGUE_ENDED` 事件。

**Task 系统**（`app/tasks/task_system.py`）：以 PostgreSQL 维护 Task 生命周期，以 Redis Streams 承载异步派发。至少定义以下 Stream：
- `stream:task:dispatch`
- `stream:task:retry`
- `stream:task:dlq`

创建任务时，业务事务内同时写入 `tasks` 和 `outbox_events`；由独立 `OutboxRelay` 将事件投递到对应 Redis Stream。禁止直接采用“先写 PostgreSQL，再写 Stream”的非原子双写流程。消费成功后 ACK；失败时依据错误类型决定重试、挂起或进入死信流。TaskMonitor 每 10 秒扫描心跳超时任务并标记失败。

**Blackboard**（`app/tasks/blackboard.py`）：无状态服务对象，所有持久化走 TaskStore。实现 `evaluate_agents`、`assign`（向 Redis Streams 投递而不是本地直接起协程）、`on_task_waiting_hitl`（高风险挂起，不标记为失败）、`resume`、`on_task_complete`、`on_task_failed`、`terminate_agent`。

**Agent 注册表**（`app/agents/registry.py`）：全局单例，`register()` / `get()` / `all()`，Blackboard 只通过此注册表查找 Agent。

**OutboxRelay**（`app/tasks/outbox_relay.py` 或 `app/infra/outbox_relay.py`）：轮询 PostgreSQL 中待发布的 `outbox_events`，投递到 Redis Streams；投递成功后更新 `published_at` / `status`，失败时指数退避重试。需要保证 relay 自身幂等，避免重复发布造成多次执行。

**WebPlatformAdapter**（`app/platform/web.py`）：实现 `PlatformAdapter`，支持普通文本响应和 SSE 流式响应，能力由 `platform_ctx.capabilities` 声明，不支持流式时自动降级。

**API 路由**（`app/api/chat.py`、`app/api/hitl.py`）：
- `POST /chat`：同步对话
- `GET /chat/stream`：SSE 流式对话
- `POST /hitl/respond`：用户确认或拒绝 HITL 请求

在 `app/main.py` 的 startup 中初始化并连接以上所有组件。

### 验收

```bash
uvicorn app.main:app --port 8000

curl -X POST http://localhost:8000/chat   -H 'Content-Type: application/json'   -d '{"text": "你好，介绍一下你自己", "session_id": "s001"}'
# 期望：返回 AI 回复

# SSE 流式
curl -N 'http://localhost:8000/chat/stream?session_id=s002'
# 另开终端发消息，期望 SSE 持续输出 delta 后以 done 结束
```

---

## Phase 5 — Sub-agent 实现

**目标**：实现 CodeAgent（OpenCode 适配器）作为第一个可用的 Sub-agent，验证任务调度链路端到端可用。

### 任务

**CodeAgent**（`app/agents/code_agent.py`）：协议适配器，不含代码执行智能，只做协议转换。调用链：创建 OpenCode session → 发送 prompt（携带结构化输出 Schema，强制 OpenCode 返回 JSON）→ 通过 httpx-sse 监听 `/global/event` SSE 流 → 按 sessionID 过滤事件 → 处理 `permission`（低风险自动 approve，高风险类型触发 `on_task_waiting_hitl`）/ `complete` / `error` 事件 → 解析结构化结果 → 回调 Blackboard → 删除 session。每收到 SSE 事件调用 `emit_heartbeat()`。

**Worker 运行模型**：为每类 Sub-agent 建立独立 Redis Streams consumer group。Worker 使用 `XREADGROUP` 读取待执行任务，处理完成后先更新 PostgreSQL，再执行 ACK。若 Worker 崩溃，可通过 pending list 重新认领。

**WebAgent**（`app/agents/web_agent.py`）：简单占位实现，`estimate_capability()` 基于关键词评分，`execute()` 只需返回最小闭环结果或调用受限的内部逻辑，**V1 不实现真正联网抓取、浏览器控制或复杂 agent loop**。

在 `app/main.py` startup 中将两个 agent 注册到 `AgentRegistry`，并在 worker 启动阶段创建相应 consumer group。

### 验收

```bash
# 前提：opencode serve --port 4096 已启动
curl -X POST http://localhost:8000/chat   -H 'Content-Type: application/json'   -d '{"text": "帮我写一段 Python 冒泡排序并运行", "session_id": "s003"}'
# 期望：任务路由到 CodeAgent，OpenCode 执行后返回代码结果
# Redis 中可观察到 task stream 消费，PostgreSQL 中 task 状态正确更新
```

---

## Phase 6 — 后台异步进化层

**目标**：实现 EventBus 及全部进化组件，使系统具备自我进化能力。前台链路不感知本阶段的存在。

### 任务

**EventBus**（`app/evolution/event_bus.py`）：实现为 Redis Streams 事件总线，支持 `emit` / `subscribe` / `ack` / `retry`。至少定义以下 Stream：
- `stream:event:dialogue`
- `stream:event:task_result`
- `stream:event:evolution`
- `stream:event:low_priority`

事件发布同样采用 Outbox Pattern：前台或任务层在提交 PostgreSQL 状态变更时，同时写入 `outbox_events`；由 relay 投递到对应事件 Stream。要求支持 consumer group、重试次数限制和低优先级事件丢弃策略。只有订阅方完成目标写入后才允许 ACK。

**SignalExtractor**（`app/evolution/signal_extractor.py`）：订阅 `DIALOGUE_ENDED`，提取 `InteractionSignal`（显式关键词检测 + 隐式行为模式），与 ObserverEngine 并行执行。

**ObserverEngine**（`app/evolution/observer.py`）：订阅 `DIALOGUE_ENDED`，批处理窗口 30 秒（最多 5 条），用 `lite.extraction` 模型抽取知识三元组，实体对齐两层（字典 + 向量模糊匹配），写入 Neo4j 和 Qdrant，emit `OBSERVATION_DONE`。

**MetaCognitionReflector**（`app/evolution/reflector.py`）：订阅 `TASK_FAILED`（P0 立即）和 `TASK_COMPLETED`（P1 批处理），用 `lite.extraction` 模型归因，产出 `Lesson`。置信度 < 0.5 丢弃。emit `LESSON_GENERATED`。

**CognitionUpdater**（`app/evolution/cognition_updater.py`）：订阅 `LESSON_GENERATED`，每 10 轮最多触发一次。能力边界问题更新 `self_cognition` 区块（成功 +0.05，失败 -0.1），世界规律写 Neo4j。调用 `CoreMemoryScheduler.write()`。

**PersonalityEvolver**（`app/evolution/personality_evolver.py`）：双速进化。快适应（session 内，不写 Core Memory，记入信号缓冲区）；慢进化（同方向信号累积 3 次触发，执行**规则晋升 / 淘汰 / 重写**，必要时低频触发 `baseline_description` 重生成，写入前做漂移检测，超限保存快照后回滚）。  
V1 中 **Behavioral Rules 是人格进化的主载体**；`traits` 若保留，只允许作为兼容字段或观测字段，不作为主要更新目标，避免回退到数值人格模型。每次进化写入 `EvolutionJournal`。参数配置参考架构文档 §5.5。

**CoreMemoryScheduler**（`app/evolution/core_memory_scheduler.py`）：统一的 Core Memory 写入入口，持有 asyncio Lock 保证串行化。Token 预算管理：超出区块配额时调用 `lite.extraction` 压缩旧条目。写入 PostgreSQL 快照后刷新 `CoreMemoryCache`，并通过 Redis 通知其他进程失效。Token 预算参考架构文档 §9。

**EvolutionJournal**（`app/evolution/evolution_journal.py`）：PostgreSQL 持久化进化事件，只追加写。

**夜间调度器**（`app/evolution/scheduler.py`）：V1 只需提供调度接口和基础任务入口，每日凌晨 3 点可执行 Qdrant 清理、低置信度规则淘汰、Core Memory 整体压缩、Neo4j 低价值关系衰减任务；不要求在 V1 实现复杂策略组合、历史效果评估或自适应调度。

**稳定性**：`app/stability/circuit_breaker.py` 实现 LLM 调用熔断器（参考架构文档 §9）；`app/stability/snapshot.py` 实现 PersonalityState 版本快照（保留最近 5 版）；`app/stability/idempotency.py` 实现 Redis Streams 消费幂等键控制。

**成长日志 API**（`app/api/journal.py`）：`GET /evolution/journal?limit=20`

### 验收

```bash
# 发送 5 条对话后检查：
# 1. Neo4j 有长期关系写入
# 2. PostgreSQL 的 core_memory_snapshots 有更新
# 3. evolution_journal 表有记录
# 4. Redis Streams 中相关事件被消费并 ACK

curl http://localhost:8000/evolution/journal?limit=10
# 期望：返回进化事件列表

# 连续发送"简洁一点"类消息，验证 session_adaptations 生效
```

---

## Phase 7 — 扩展注册层与整合

**目标**：建立 Tool、Hook、MCP、Skill 的后期注册机制；整合完整启动流程；提供一键启动脚本。本阶段完成后，后续扩展只需注册，不改核心代码。

### 任务

**MCP 工具适配器**（`app/tools/mcp_adapter.py`）：从配置文件（`mcp_servers.json` 或 `.env`）读取 MCP Server 列表，调用 `tools/list` 接口获取工具定义，逐一包装后注册到 `ToolRegistry`。调用时通过 `tools/call` 转发。**V1 只要求注册框架、配置读取、最小占位调用链路**，不要求完整协议兼容、认证协商、会话复用或生态管理能力。

**Skill 加载器**（`app/skills/loader.py`）：扫描 `./skills/` 目录下的 YAML/JSON 文件，按 `type` 字段分发注册（`sub_agent` → `AgentRegistry`，`tool` → `ToolRegistry`）。**V1 只要求 manifest/配置装载与注册生效**，不要求复杂技能编排器、技能市场、在线热更新。

**`app/main.py` 完整启动流程**：按顺序初始化所有组件（PostgreSQL / Neo4j / Redis / Qdrant 连接 → Provider → Memory → EventBus → Agents → Evolution 组件 → TaskMonitor → Scheduler → Skill 加载 → MCP 加载），并将路由全部注册到 FastAPI。

**`start.sh`**：一键拉起 Docker Compose、OpenCode Server、FastAPI 服务，退出时清理子进程。

**扩展性验证**：不修改任何现有文件，仅通过注册接口添加一个新 Tool（如 `get_current_time`），验证 Soul Engine 可以调用它。

### 验收

```bash
bash start.sh
curl http://localhost:8000/health
# 期望：所有子系统状态正常

# 扩展性验收：新增工具不改核心代码
python -c "
from app.tools.registry import tool_registry

@tool_registry.register(name='get_time', description='获取当前时间', schema={})
async def get_time(params):
    from datetime import datetime
    return {'time': datetime.now().isoformat()}

assert tool_registry.get('get_time') is not None
print('Extensibility OK')
"
```

---

## 附：Phase 依赖关系

```text
Phase 0 （脚手架）
  └── Phase 1 （接口层）
        ├── Phase 2 （Provider）
        │     └── Phase 3 （记忆系统）
        │           └── Phase 4 （前台链路）
        │                 └── Phase 5 （Sub-agents）
        │                       └── Phase 6 （进化层）
        │                             └── Phase 7 （整合）
        └── Phase 4 也依赖 Phase 1
```

每个 Phase 完成并通过验收后，再开始下一个 Phase。

---

*PLAN.md — 面向 Codex 按阶段执行，任务边界最终版（PostgreSQL + Neo4j + Redis Streams + Qdrant） | 参考架构 v3.4*
