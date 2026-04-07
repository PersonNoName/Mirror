# Main Agent 精简架构设计文档

> **版本**：v3.3（基于 v3.2 更新）
> **用途**：供 AI 进行代码架构编写参考，涵盖宏观架构、模块设计、数据结构、进化机制与稳定性保障。
> **精简原则**：保留所有核心功能，合并冗余模块，推迟非必要的边界防护至第二期。
> **v3.2 更新内容**：重构人格进化系统——以「行为规则」替代数值特质作为主要进化载体；引入「双速进化」机制（快适应+慢进化）；新增进化可见性成长日志（EvolutionJournal）。
> **v3.3 更新内容**：Token 预算提升至 5000 并引入动态储备池；Core Memory 语义从 per-session 改为 per-user；补充 InteractionSignal 信号抽取器定义；完善规则语义去重、进化链式触发、SSE 连接复用、分关系类型置信度衰减等细节。

---

## 目录

1. [整体设计原则](#1-整体设计原则)
2. [宏观架构：三层结构](#2-宏观架构三层结构)
3. [前台同步层](#3-前台同步层)
   - 3.1 [记忆挂载区](#31-记忆挂载区)
   - 3.2 [核心推理引擎（Soul Engine）](#32-核心推理引擎soul-engine)
   - 3.3 [动作路由区](#33-动作路由区)
4. [任务执行层](#4-任务执行层)
   - 4.1 [Task 系统](#41-task-系统)
   - 4.2 [Blackboard 黑板](#42-blackboard-黑板)
   - 4.3 [Sub-agents](#43-sub-agents)
5. [后台异步进化层](#5-后台异步进化层)
   - 5.1 [异步事件总线](#51-异步事件总线)
   - 5.2 [Observer 后台观察引擎](#52-observer-后台观察引擎)
   - 5.3 [元认知反思器](#53-元认知反思器)
   - 5.4 [认知进化器（统一）](#54-认知进化器统一)
   - 5.5 [人格进化器](#55-人格进化器)
   - 5.6 [Core Memory 写入调度器](#56-core-memory-写入调度器)
   - 5.7 [进化可见性：成长日志](#57-进化可见性成长日志)
6. [持久化双轨记忆库](#6-持久化双轨记忆库)
7. [Core Memory 结构设计](#7-core-memory-结构设计)
8. [进化闭环与协同触发链路](#8-进化闭环与协同触发链路)
9. [稳定性保障机制](#9-稳定性保障机制)
10. [延迟预算分配](#10-延迟预算分配)
11. [数据结构定义](#11-数据结构定义)
12. [模块依赖关系](#12-模块依赖关系)
13. [精简变更说明](#13-精简变更说明)

---

## 1. 整体设计原则

| 原则         | 说明                                                                                  |
| ---------- | ----------------------------------------------------------------------------------- |
| **快慢分离**   | 前台同步层极速响应（<2s），后台异步层从容进化，两者通过事件总线单向解耦，前台永不等待后台                                      |
| **拒绝信息膨胀** | Core Memory 强制 Token 预算上限（5000 tokens），四区块基础配额 + 动态储备池，通过 LLM 压缩旧条目，Prompt 始终保持精准可控 |
| **高内聚低耦合** | 记忆管理、主控推理、进化引擎完全解耦，支持独立单元测试和模型替换                                                    |
| **进化不阻塞**  | 所有进化行为发生在异步后台，进化结果通过 Core Memory 在下次推理时自然生效                                         |
| **渐进不突变**  | 人格与认知进化采用小学习率+惯性更新，配合漂移检测与版本回滚，防止性格突变                                               |
| **绝对不遗忘**  | 引入"钉选（Pinning）"机制，确保用户核心禁忌与绝对约束免疫数据衰减与压缩                                            |

---

## 2. 宏观架构：三层结构

```
┌────────────────────────────────────────────────────────┐
│                     用户 / User                         │
│              ↑ HITL弹窗        自然语言请求 ↓           │
└────────────────────────────────────────────────────────┘
                          │
┌────────────────────────────────────────────────────────┐
│             前台同步层（目标：极速响应 <2s）              │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────┐  │
│  │  记忆挂载区  │→ │  核心推理引擎     │→ │ 动作路由区 │  │
│  │  <50ms 检索 │  │  Soul Engine     │  │  Router   │  │
│  └─────────────┘  └──────────────────┘  └───────────┘  │
└────────────────────────────────────────────────────────┘
         ↑ 实时检索回路                  ↓ 发布 Task
┌────────────────────────────────────────────────────────┐
│           任务执行层（目标：可观测、可调度）              │
│  ┌──────────────────────┐  ┌───────────────────────┐   │
│  │       Task 系统       │→ │    Blackboard 黑板     │   │
│  │  心跳检活 + 优先级队列 │  │  DAG + Sub-agent 委派  │   │
│  └──────────────────────┘  └───────────────────────┘   │
│                                    ↓ 委派 / ↑ 完成      │
│                             ┌─────────────────────┐    │
│                             │  Sub-agents 工具层   │    │
│                             └─────────────────────┘    │
└────────────────────────────────────────────────────────┘
         ↓ 对话副本（异步）    ↓ 任务完成事件（异步）
┌────────────────────────────────────────────────────────┐
│        后台异步进化层（目标：永不阻塞前台）               │
│                 ┌────────────────┐                     │
│                 │   异步事件总线  │                     │
│                 └────────────────┘                     │
│        ↓           ↓           ↓           ↓           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Observer │ │元认知反思│ │ 认知进化 │ │ 人格进化 │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│                 ┌────────────────────┐                 │
│                 │  稳定性守卫层       │                 │
│                 │ 熔断·限速·幂等·预算 │                 │
│                 └────────────────────┘                 │
│                 ┌────────────────────┐                 │
│                 │ Core Memory 调度器  │                 │
│                 └────────────────────┘                 │
└────────────────────────────────────────────────────────┘
                          ↓ 写入
┌────────────────────────────────────────────────────────┐
│                  持久化双轨记忆库                        │
│  ┌───────────────────────┐  ┌──────────────────────┐   │
│  │  Graph DB（偏好图谱）  │  │  Vector DB（经验语义） │   │
│  └───────────────────────┘  └──────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

---

## 3. 前台同步层

### 3.1 记忆挂载区

**职责**：在 LLM 推理前，以最低延迟将相关记忆注入 Context。

#### 检索架构（两级流水线）

> **精简说明**：移除 Cross-Encoder 强制 Rerank（Level 3），改为按需触发。ANN 结果置信度方差大时才走 Rerank，正常路径直接 Top K 截断，节省 30~50ms。

```
用户输入
   │
   ├─── Level 0：Core Memory 直接读取（内存）
   │    └─ 延迟：0ms（常驻内存，每次推理必定注入）
   │
   ├─── Level 1：本地 LRU 缓存命中检测
   │    └─ 延迟：<1ms（最近 100 条对话的检索结果缓存）
   │
   ├─── Level 2：Vector DB ANN 粗排检索
   │    └─ 延迟：10~30ms（HNSW 索引，召回 Top 20，截取 Top 8）
   │
   └─── Level 2.5（按需）：Cross-Encoder Rerank
        └─ 仅当 Top 20 相似度方差 > 阈值时触发，延迟 30~50ms
```

#### Core Memory 缓存策略

```python
class CoreMemoryCache:
    """
    Core Memory 常驻内存，进程启动时加载，进化写入后立即刷新。
    注意：Core Memory 是 per-user 的（非 per-session），同一用户的所有
    活跃 Session 共享同一份 Core Memory。进化写入后需通知所有活跃 Session 刷新。
    """
    _cache: dict  # {user_id: CoreMemory}
    _active_sessions: dict  # {user_id: set[session_id]}，用于广播 invalidation

    def get(self, user_id: str) -> CoreMemory:
        return self._cache[user_id]  # 始终命中，无 DB 查询

    def invalidate(self, user_id: str):
        # 进化器写入 Core Memory 后调用，所有该用户的活跃 Session 下次推理自动获取最新版本
        self._cache[user_id] = self._load_from_db(user_id)
```

#### Vector 检索配置

```python
VECTOR_RETRIEVAL_CONFIG = {
    "index_type": "HNSW",
    "ef_search": 64,
    "recall_top_k": 20,
    "final_top_k": 8,
    "rerank_model": "bge-reranker-v2-m3",    # 仅按需调用
    "rerank_variance_threshold": 0.15,        # 方差超过此值才触发 Rerank
    "score_threshold": 0.5,
    "namespace_priority": [
        "experience",
        "self_cognition",
        "world_model",
        "dialogue_fragment",
    ],
    "max_total_tokens": 1200,
}
```

#### Context 组装顺序

```
System Prompt
   └── Core Memory（4区块+动态储备池，≤5000 tokens，必注入，免疫淘汰）
       └── 自我认知区(≤1000) → 世界观区(≤1000) → 人格基调区(≤800) → 任务经验区(≤1200)
       └── 动态储备池(1000)：任一区块超限时可借用
   └── 行为规则（Behavioral Rules，≤10 条，从人格进化器产出）
       └── 自然语言指令，LLM 可直接执行
   └── Session 适应（仅当前会话有效，≤5 条，超限时替换最旧条目）

Session Raw Context（当前 Session 最近 5 轮原文，≤800 tokens）
   └── 不依赖 Vector DB，解决 Observer 批处理延迟导致的近期对话检索缺失

Retrieved Context（≤1200 tokens，按相关性排序）
   └── 相关经验 → 相关偏好 → 相关对话片段

User Message
```

---

### 3.2 核心推理引擎（Soul Engine）

**职责**：生成 `inner_thoughts`，保持独立人格，决定动作输出。

#### Prompt 构建规则

```python
SOUL_SYSTEM_PROMPT_TEMPLATE = """
你是一个平等的合作者，不是用户的仆人。

## 你的自我认知
{core_memory.self_cognition}

## 你对世界的理解
{core_memory.world_model}

## 你的人格基调
{core_memory.personality.baseline_description}

## 你从交互中学到的行为规则（必须遵守）
{behavioral_rules}

## 本次对话适应（仅当前 Session 有效）
{session_adaptations}

## 你积累的经验
{core_memory.task_experience}

## 行为约束
- 禁止使用讨好性词汇（"当然！"、"好的！"、"我很乐意..."）
- 若认为用户请求不合理，必须在 inner_thoughts 中记录异议
- 先思考，再行动：任何动作前必须生成 <inner_thoughts>

## 输出格式
<inner_thoughts>
[你的内部独白：评估请求合理性、规划行动路径、预判风险]
</inner_thoughts>
<action>
[one of: direct_reply | tool_call | publish_task | hitl_relay]
</action>
<content>
[对应动作的内容]
</content>
"""
```

#### 动作类型定义

| 动作类型 | 触发条件 | 输出内容 |
|----------|----------|----------|
| `direct_reply` | 可直接回答，无需外部工具 | 回复文本 |
| `tool_call` | 需要修改 Core Memory 或查询外部信息 | Tool Call JSON |
| `publish_task` | 需要委派给 Sub-agent 执行 | 标准化 Task JSON |
| `hitl_relay` | 收到 Sub-agent 权限请求，需用户确认 | 权限申请描述 |

---

### 3.3 动作路由区

```python
class ActionRouter:
    async def route(self, action: Action) -> None:
        match action.type:
            case "direct_reply":
                await self.reply_to_user(action.content)
                await self.event_bus.emit("dialogue_ended", action.context)

            case "publish_task":
                task = await self.task_system.create(action.content)
                best_agent, cap_score = await self.blackboard.evaluate_agents(task)
                if cap_score < 0.3:
                    fallback_msg = f"当前工具无法稳妥完成此任务（置信度 {cap_score}），请求指示。"
                    result = await self.hitl_gateway.ask_user(fallback_msg)
                    await self.soul_engine.continue_with(result)
                elif cap_score < 0.5:
                    # 中置信度：尝试执行，但提前通知用户可能不完美
                    await self.blackboard.assign(task, best_agent)
                    await self.reply_to_user(
                        f"正在尝试处理，但置信度偏低（{cap_score:.1f}），结果可能需要你确认。"
                    )
                else:
                    await self.blackboard.assign(task, best_agent)

            case "hitl_relay":
                result = await self.hitl_gateway.ask_user(action.content)
                await self.blackboard.resume(action.task_id, result)

            case "tool_call":
                result = await self.tool_executor.run(action.content)
                await self.soul_engine.continue_with(result)
```

---

## 4. 任务执行层

### 4.1 Task 系统

#### 核心数据结构

```python
@dataclass
class Task:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_task_id: Optional[str] = None
    children_task_ids: list[str] = field(default_factory=list)
    created_by: str = "main_agent"
    assigned_to: str = ""
    intent: str = ""
    prompt_snapshot: str = ""       # 派发时的完整 Prompt（反思素材）
    status: Literal[
        "pending", "running", "done", "failed", "interrupted", "cancelled"
    ] = "pending"
    priority: int = 1               # 0=紧急, 1=正常, 2=低优
    depends_on: list[str] = field(default_factory=list)
    result: Optional[dict] = None
    error_trace: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    timeout_seconds: int = 300
    last_heartbeat_at: datetime = field(default_factory=datetime.utcnow)
    heartbeat_timeout: int = 30
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)
```

#### 状态机与级联取消

```
pending ──→ running ──→ done
                   └──→ failed ──→ (retry) pending
                               └──→ interrupted ──→ [级联取消 children]
```

```python
class TaskDAG:
    async def cascade_cancel(self, task_id: str):
        task = await self.get_task(task_id)
        for child_id in task.children_task_ids:
            child = await self.get_task(child_id)
            if child.status in ["pending", "running"]:
                child.status = "cancelled"
                await self.blackboard.terminate_agent(child.assigned_to)
                await self.task_store.update(child)
                await self.cascade_cancel(child_id)  # 递归
```

#### 优先级队列

```python
class TaskQueue:
    """三级优先级队列 + 依赖 DAG 调度"""
    def __init__(self):
        self.queues = {0: asyncio.PriorityQueue(),
                       1: asyncio.PriorityQueue(),
                       2: asyncio.PriorityQueue()}
        self.dag = TaskDAG()

    async def enqueue(self, task: Task):
        if self.dag.all_deps_done(task):
            await self.queues[task.priority].put(task)
        else:
            self.dag.wait(task)

    async def on_task_done(self, task_id: str):
        unblocked = self.dag.unblock(task_id)
        for t in unblocked:
            await self.enqueue(t)
```

#### 超时与心跳检活

```python
RETRY_CONFIG = {
    "max_retries": 2,
    "backoff_strategy": "exponential",
    "backoff_base_seconds": 5,
    "timeout_by_domain": {
        "code_execution": 300,
        "file_operation": 60,
        "web_search": 30,
        "default": 120,
    }
}

class TaskMonitor:
    """防止 Sub-agent 崩溃导致任务永久卡在 running 状态"""
    async def start_sweeper(self):
        while True:
            await asyncio.sleep(10)
            now = datetime.utcnow()
            for task in await self.task_store.get_by_status("running"):
                if (now - task.last_heartbeat_at).seconds > task.heartbeat_timeout:
                    await self.blackboard.on_task_failed(
                        task, error="Agent Heartbeat Lost"
                    )
```

---

### 4.2 Blackboard 黑板

**职责**：任务状态可视化中心，协调 Sub-agent 执行，广播完成事件。Blackboard 本身是**无状态服务对象**——不持有任何任务数据，所有持久化统一走 `task_store`，便于横向扩展。

#### 设计原则

- `evaluate_agents()` → `assign()` 是主路径：评分后选最优 agent，分数不足则升级 HITL
- `on_task_complete()` / `on_task_failed()` 是对称的两条回调路径，结构相同，仅事件优先级不同
- `resume()` 是 HITL 专用恢复入口，Sub-agent 等待期间任务挂起，用户响应后由 Blackboard 重注入
- 对 EventBus 完全解耦：Blackboard 只管 `emit()`，不知道下游订阅者是谁

```python
class Blackboard:

    async def evaluate_agents(self, task: Task) -> tuple[SubAgent, float]:
        """遍历 agent_registry，取最高能力评分的 agent"""
        best_agent, best_score = None, 0.0
        for agent in self.agent_registry.values():
            score = await agent.estimate_capability(task)
            if score > best_score:
                best_agent, best_score = agent, score
        return best_agent, best_score

    async def assign(self, task: Task) -> None:
        """将 Task 委派给指定 Sub-agent，不阻塞等待结果"""
        agent = self.agent_registry.get(task.assigned_to)
        task.status = "running"
        await self.task_store.update(task)
        asyncio.create_task(agent.execute(task))   # 异步启动，立即返回

    async def resume(self, task_id: str, hitl_result: dict) -> None:
        """HITL 用户响应后恢复挂起的任务"""
        task = await self.task_store.get(task_id)
        task.metadata["hitl_result"] = hitl_result
        agent = self.agent_registry.get(task.assigned_to)
        asyncio.create_task(agent.resume(task, hitl_result))

    async def on_task_complete(self, task: Task) -> None:
        """任务完成：更新状态 + 广播 P1 事件"""
        task.status = "done"
        await self.task_store.update(task)
        await self.event_bus.emit("task_completed", {"task": task})

    async def on_task_failed(self, task: Task, error: str) -> None:
        """任务失败：记录 error_trace + 广播 P0 立即反思事件"""
        task.status = "failed"
        task.error_trace = error
        await self.task_store.update(task)
        await self.event_bus.emit("task_failed", {
            "task": task,
            "priority": 0,   # P0：失败立即触发元认知反思
        })

    async def terminate_agent(self, agent_name: str) -> None:
        """TaskDAG 级联取消时调用，释放 agent 占用的资源"""
        agent = self.agent_registry.get(agent_name)
        if agent:
            await agent.cancel()
```

#### 失败分类处理

Sub-agent 回调 `on_task_failed` 时应在 `error_trace` 中区分失败类型，以便 `MetaCognitionReflector` 归因：

| 失败类型 | error_trace 标识 | 重试策略 |
|---------|-----------------|---------|
| 网络超时 / OOM | `RETRYABLE: ...` | 指数退避重入队 |
| 任务本身不可完成 | `FATAL: ...` | 直接 `interrupted`，不消耗重试次数 |
| 心跳丢失（进程崩溃） | `Agent Heartbeat Lost` | 视为 RETRYABLE |
| 权限被用户拒绝 | `HITL_REJECTED: ...` | 直接 `interrupted` |

---

### 4.3 Sub-agents

#### 基类接口（ABC）

所有 Sub-agent 实现统一接口，便于 `agent_registry` 统一管理与 `estimate_capability` 打分。

```python
from abc import ABC, abstractmethod

class SubAgent(ABC):
    name: str
    domain: str

    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """执行任务主循环，需定期调用 emit_heartbeat()"""
        pass

    @abstractmethod
    async def estimate_capability(self, task: Task) -> float:
        """返回 0~1 的能力评分，必须轻量（无网络调用，<10ms）"""
        pass

    async def cancel(self) -> None:
        """Blackboard 级联取消时调用，子类可覆盖以释放外部资源"""
        pass

    async def emit_heartbeat(self, task: Task) -> None:
        """刷新心跳时间戳，防止 TaskMonitor 误判超时"""
        task.last_heartbeat_at = datetime.utcnow()
        await self.task_store.update_heartbeat(task.id, task.last_heartbeat_at)
```

---

#### CodeAgent：OpenCode HTTP 适配器

**定位**：`CodeAgent` 是一个**协议适配器**，本身不含任何代码执行智能。它负责将系统内部的 `Task` 协议翻译为 OpenCode HTTP API 调用，并将结果翻译回 `TaskResult`。代码执行能力完全由 OpenCode 提供。

**技术选型**：Python `httpx`（异步 HTTP 客户端）+ `httpx-sse`（SSE 流解析），与主系统 `asyncio` 架构天然契合，无需引入 Node.js 技术栈。

**OpenCode 启动方式**：以 headless server 模式常驻运行，避免每次任务冷启动开销：

```bash
# 系统启动时拉起，常驻后台
opencode serve --port 4096 --hostname 127.0.0.1
```

#### estimate_capability()

必须轻量，不能有任何网络调用。两级评分：关键词快速匹配 + Core Memory 历史成功率加权。

```python
CODE_KEYWORDS = {
    "高权重": ["代码", "编程", "实现", "脚本", "debug", "调试", "重构", "函数", "类", "算法"],
    "低权重": ["文件", "运行", "执行", "测试"],
    "互斥": ["搜索", "网页", "天气", "新闻", "翻译"],  # 出现时大幅降分，减少与其他 Agent 评分重叠
}

async def estimate_capability(self, task: Task) -> float:
    text = task.intent.lower()
    keyword_score = 0.0
    for kw in CODE_KEYWORDS["高权重"]:
        if kw in text:
            keyword_score = min(1.0, keyword_score + 0.2)
    for kw in CODE_KEYWORDS["低权重"]:
        if kw in text:
            keyword_score = min(1.0, keyword_score + 0.1)
    for kw in CODE_KEYWORDS["互斥"]:
        if kw in text:
            keyword_score = max(0.0, keyword_score - 0.3)

    # 叠加 Core Memory 历史成功率
    history_confidence = await self.core_memory_cache.get_capability_confidence("code")
    return keyword_score * 0.6 + history_confidence * 0.4
```

#### execute()：完整 HTTP 调用流程

```python
import httpx
from httpx_sse import aconnect_sse

OPENCODE_BASE_URL = "http://127.0.0.1:4096"

# TaskResult 的 JSON Schema 约束，强制 OpenCode 返回结构化结果
TASK_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":    {"type": "string", "description": "执行结果摘要"},
        "files_changed": {"type": "array", "items": {"type": "string"}, "description": "改动的文件路径列表"},
        "success":    {"type": "boolean"},
        "error_type": {"type": "string", "enum": ["RETRYABLE", "FATAL", "NONE"]},
        "error_msg":  {"type": "string"},
    },
    "required": ["summary", "success", "error_type"],
}

class CodeAgent(SubAgent):
    name = "code_agent"
    domain = "code"

    async def execute(self, task: Task) -> TaskResult:
        async with httpx.AsyncClient(timeout=None) as client:
            # ── 1. 创建独立 session（一个 Task 对应一个 session）──
            resp = await client.post(
                f"{OPENCODE_BASE_URL}/session",
                json={"title": f"task:{task.id}"},
            )
            resp.raise_for_status()
            session_id = resp.json()["id"]

            try:
                # ── 2. 构建 prompt 并写入 task.prompt_snapshot（供反思器使用）──
                prompt = self._build_prompt(task)
                task.prompt_snapshot = prompt
                await self.task_store.update(task)

                # ── 3. 异步发送 prompt（非阻塞，204 No Content）──
                await client.post(
                    f"{OPENCODE_BASE_URL}/session/{session_id}/prompt_async",
                    json={
                        "parts": [{"type": "text", "text": prompt}],
                        "format": {"type": "json_schema", "schema": TASK_RESULT_SCHEMA},
                    },
                )

                # ── 4. 订阅 SSE 事件流，边收边打心跳，边处理权限请求 ──
                result = await self._listen_until_done(client, session_id, task)
                return result

            finally:
                # ── 5. 无论成功失败，清理 session，释放 OpenCode 资源 ──
                await client.delete(f"{OPENCODE_BASE_URL}/session/{session_id}")

    async def _listen_until_done(
        self, client: httpx.AsyncClient, session_id: str, task: Task
    ) -> TaskResult:
        """监听 SSE 全局事件流，直到当前 session 完成"""
        async with aconnect_sse(
            client, "GET", f"{OPENCODE_BASE_URL}/global/event"
        ) as event_source:
            async for sse in event_source.aiter_sse():
                # 每条 SSE event 都刷新心跳，防止 TaskMonitor 误判
                await self.emit_heartbeat(task)

                data = json.loads(sse.data)
                if data.get("sessionID") != session_id:
                    continue   # 过滤其他 session 的事件

                event_type = data.get("type")

                # ── 权限请求：低风险自动 approve，高风险升级 HITL ──
                if event_type == "permission":
                    await self._handle_permission(client, session_id, task, data)

                # ── session 完成：取结果并返回 ──
                elif event_type in ("complete", "session.complete"):
                    return await self._fetch_result(client, session_id, task)

                # ── session 出错：直接标记失败 ──
                elif event_type == "error":
                    error_msg = data.get("message", "OpenCode internal error")
                    await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
                    return TaskResult(task_id=task.id, status="failed", error_trace=error_msg)

    async def _handle_permission(
        self, client: httpx.AsyncClient, session_id: str, task: Task, event: dict
    ) -> None:
        """
        权限请求分级处理：
        - 低风险（文件读写、常规 shell）→ 自动 approve
        - 高风险（网络请求、危险命令）→ 升级为 hitl_relay，挂起等待用户确认
        """
        permission_id = event["permissionID"]
        permission_type = event.get("permissionType", "")

        HIGH_RISK = {"network_request", "dangerous_shell", "delete_files"}
        if permission_type in HIGH_RISK:
            # 挂起任务，通过 Blackboard → ActionRouter → hitl_relay 弹窗给用户
            await self.blackboard.on_task_failed(
                task, f"HITL_REQUIRED: permission={permission_type}"
            )
            return

        # 低风险：自动 approve
        await client.post(
            f"{OPENCODE_BASE_URL}/session/{session_id}/permissions/{permission_id}",
            json={"response": "approve", "remember": False},
        )

    async def _fetch_result(
        self, client: httpx.AsyncClient, session_id: str, task: Task
    ) -> TaskResult:
        """取最终消息，解析 structured_output，转换为 TaskResult"""
        resp = await client.get(f"{OPENCODE_BASE_URL}/session/{session_id}/message")
        messages = resp.json()

        # 取最后一条 assistant 消息的 structured_output
        structured = None
        for msg in reversed(messages):
            if msg["info"].get("role") == "assistant":
                structured = msg["info"].get("structured_output")
                break

        if structured and structured.get("success"):
            await self.blackboard.on_task_complete(task)
            return TaskResult(
                task_id=task.id,
                status="done",
                result={
                    "summary": structured["summary"],
                    "files_changed": structured.get("files_changed", []),
                },
            )
        else:
            error_type = structured.get("error_type", "RETRYABLE") if structured else "RETRYABLE"
            error_msg  = structured.get("error_msg", "unknown") if structured else "no structured output"
            full_error = f"{error_type}: {error_msg}"
            await self.blackboard.on_task_failed(task, full_error)
            return TaskResult(task_id=task.id, status="failed", error_trace=full_error)

    def _build_prompt(self, task: Task) -> str:
        return f"""任务意图：{task.intent}

工作目录：{task.metadata.get('working_dir', '.')}

约束条件：
{task.metadata.get('constraints', '无特殊约束')}

请完成上述任务，并以 JSON 格式返回执行结果。"""
```

#### 重试策略说明

> **SSE 连接复用优化**：当多个 CodeAgent 任务并发执行时，每个 Task 都独立订阅 `/global/event` SSE 流，导致 O(N²) 事件处理。生产环境建议引入进程级 SSE 连接复用层：

```python
class SSEMultiplexer:
    """进程级单例：一个全局 SSE 连接，按 sessionID 分发事件到各 Task 监听器"""
    _listeners: dict[str, asyncio.Queue]  # {session_id: event_queue}

    async def start(self):
        """启动全局 SSE 监听，持续运行"""
        async with httpx.AsyncClient(timeout=None) as client:
            async with aconnect_sse(
                client, "GET", f"{OPENCODE_BASE_URL}/global/event"
            ) as source:
                async for sse in source.aiter_sse():
                    data = json.loads(sse.data)
                    sid = data.get("sessionID")
                    if sid and sid in self._listeners:
                        await self._listeners[sid].put(data)

    def subscribe(self, session_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self._listeners[session_id] = q
        return q

    def unsubscribe(self, session_id: str):
        self._listeners.pop(session_id, None)
```

`error_type` 字段由 CodeAgent 在解析 OpenCode 结果时填写，直接影响 `TaskSystem` 的重试决策：

| error_type | 含义 | TaskSystem 行为 |
|-----------|------|----------------|
| `NONE` | 成功 | 标记 `done` |
| `RETRYABLE` | 临时性失败（超时、OOM） | 指数退避后重入队 |
| `FATAL` | 任务本身不可完成 | 直接 `interrupted`，不消耗重试次数 |
| `HITL_REQUIRED` | 需要用户授权 | 挂起，等待 `hitl_relay` 结果后 `resume` |

#### 其他 Sub-agent（WebAgent / FileAgent / …）

非代码类 agent 结构更简单，内置工具自闭环，不依赖外部进程：

```python
class WebAgent(SubAgent):
    name = "web_agent"
    domain = "search"

    async def estimate_capability(self, task: Task) -> float:
        keywords = ["搜索", "查询", "网络", "最新", "新闻", "search"]
        score = sum(0.2 for kw in keywords if kw in task.intent.lower())
        return min(1.0, score)

    async def execute(self, task: Task) -> TaskResult:
        # 直接调用 LLM + 搜索工具，内置 agent loop
        # 每次工具调用后 emit_heartbeat()
        ...
```

新增 agent 只需继承 `SubAgent`，实现 `execute()` 和 `estimate_capability()`，在 `agent_registry` 注册即可，Blackboard 无需修改。

---

## 5. 后台异步进化层

### 5.1 异步事件总线

```python
class EventBus:
    EVENT_TYPES = [
        "dialogue_ended",   # 对话结束 → 触发 Observer
        "task_completed",   # 任务完成 → 触发元认知反思（P1）
        "task_failed",      # 任务失败 → 触发元认知反思（P0，立即）
        "hitl_feedback",    # 用户 HITL 反馈 → 触发人格信号
        "evolution_done",   # 进化完成 → 触发 Core Memory 写入
    ]

    async def emit(self, event_type: str, payload: dict) -> None:
        await self.queue.put(Event(type=event_type, payload=payload))

    async def subscribe(self, event_type: str, handler: Callable) -> None:
        self.handlers[event_type].append(handler)
```

**背压保护**：

```python
EVENT_BUS_CONFIG = {
    "max_queue_depth": 1000,
    "drop_policy": "drop_lowest_priority",
    "alert_threshold": 800,
}
```

---

### 5.2 Observer 后台观察引擎

**职责**：从对话中异步抽取知识三元组，写入 Graph DB 与 Vector DB。

#### 实体对齐（两层）

> **精简说明**：移除 Layer 3 异步 LLM 裁判官，初期将 0.7~0.95 相似度的疑似别名直接创建为独立节点，待数据积累后再按需合并。

```
输入：原始实体名称（如 "vsc"、"Pyhton"）
   │
   ├── Layer 1：字典查找（~1ms）
   │   └─ 命中 → 直接映射
   │   └─ 未命中 → 进入 Layer 2
   │
   └── Layer 2：向量模糊匹配（~20ms）
       └─ 相似度 > 0.95 → 直接对齐
       └─ 相似度 < 0.95 → 创建独立节点（后期可批量合并）
```

#### 知识抽取 Prompt

```python
KNOWLEDGE_EXTRACTION_PROMPT = """
从以下对话中抽取结构化知识三元组。

约束：
- 只抽取有置信度的事实，不推断
- Subject 必须是明确的实体（用户、工具、环境）
- Relation 使用预定义词表：PREFERS / DISLIKES / USES / KNOWS / HAS_CONSTRAINT / IS_GOOD_AT / IS_WEAK_AT
- 若无可抽取内容，返回空数组

输出格式（JSON 数组）：
[
  {"subject": "用户", "relation": "PREFERS", "object": "Python", "confidence": 0.9},
  {"subject": "CodeAgent", "relation": "IS_WEAK_AT", "object": "并发任务", "confidence": 0.75}
]

对话内容：
{dialogue}
"""
```

#### 批处理策略

```python
class ObserverEngine:
    BATCH_WINDOW_SECONDS = 30
    MAX_BATCH_SIZE = 5

    async def process(self, event: Event):
        dialogue = event.payload["dialogue"]
        if not await self._is_salient(dialogue):
                                           │  成长日志记录            │
                                      │  用户可查 / AI 可引用    │
                                      └────────────────────────┘
```

```python
class PersonalityEvolver:
    """双速进化：快适应（Session 级）+ 慢进化（跨 Session）"""

    # ── 快适应配置 ──
    FAST_WINDOW_SIZE = 3            # 最近 3 轮对话的信号窗口
    FAST_MAX_ADAPTATIONS = 5        # 单 Session 最多 5 条快适应规则，超限替换最旧

    # ── 慢进化配置 ──
    SLOW_UPDATE_FREQUENCY = 10      # 每 10 轮对话最多触发一次
    SIGNAL_CONFIRMATION = 3         # 同方向信号累积 3 次才确认
    RULE_PROMOTE_THRESHOLD = 0.7    # 快适应规则置信度达到此值时晋升为持久规则
    RULE_DECAY_THRESHOLD = 0.3      # 低于此值的规则自动清理

    # ── 稳定性配置 ──
    LEARNING_RATE = 0.05
    DRIFT_THRESHOLD = 0.3
    HARD_GUARDRAILS = {
        "autonomy": (0.2, 0.95),
        "warmth":   (0.3, 1.0),
        "caution":  (0.4, 0.9),
    }OMPT.format(
                task_snapshot=task.prompt_snapshot,
                task_result=task.result,
                error_trace=task.error_trace,
                domain=task.metadata.get("domain", "unknown"),
            )
        )
        if result["confidence"] < 0.5:
            return None  # 低置信度反思直接丢弃，防止认知污染

        lesson = Lesson(
            task_id=task.id,
            domain=result.get("domain", task.metadata.get("domain")),
            outcome=task.status,
            root_cause=result["root_cause"],
            lesson_text=result["lesson"],
            is_agent_capability_issue=result["is_agent_capability_issue"],
        )
        await self.event_bus.emit("evolution_done", {"lesson": lesson})
        return lesson
```

---

### 5.4 认知进化器（统一）

> **精简说明**：将原来的 `SelfCognitionUpdater` + `WorldModelUpdater` 合并为一个 `CognitionUpdater`，通过 `lesson` 内容自动判断写入哪个区块，减少一个独立类。
>
> **World Model 写入路径统一**：Graph DB 为真实数据源，`CoreMemory.world_model` 仅作为只读快照，由调度器在写入时从 Graph DB 合成，不再双写。

```python
class CognitionUpdater:
    """统一处理自我认知与世界观更新"""

    async def update(self, lesson: Lesson):
        if lesson.is_agent_capability_issue:
            await self._update_self_cognition(lesson)
        else:
            await self._update_world_model(lesson)

    async def _update_self_cognition(self, lesson: Lesson):
        current = await self.core_memory.get_self_cognition()
        domain = lesson.domain
        entry = current.capability_map.get(domain)

        if entry:
            if lesson.outcome == "done":
                entry.confidence = min(1.0, entry.confidence + 0.05)
            else:
                entry.confidence = max(0.0, entry.confidence - 0.1)
                if lesson.root_cause not in entry.known_limits:
                    entry.known_limits.append(lesson.root_cause)
        else:
            current.capability_map[domain] = CapabilityEntry(
                domain=domain,
                confidence=0.5 if lesson.outcome == "done" else 0.3,
                known_limits=[] if lesson.outcome == "done" else [lesson.root_cause],
            )

        await self.core_memory_scheduler.write("self_cognition", current)

    async def _update_world_model(self, lesson: Lesson):
        """规律性结论写入 Graph DB，Core Memory 快照由调度器合成"""
        if lesson.is_pattern:
            existing = await self.graph_db.get_relation(lesson.subject, lesson.object)
            if existing and self._is_conflict(existing, lesson.relation):
                resolved = await self._resolve_conflict(existing, lesson)
                await self.graph_db.upsert_relation(**resolved)
            else:
                await self.graph_db.upsert_relation(
                    subject=lesson.subject,
                    relation=lesson.relation,
                    object=lesson.object,
                    confidence=lesson.confidence,
                )
```

**触发频率**：认知进化器每 10 轮对话最多触发一次完整更新。

---

### 5.5 人格进化器

**职责**：基于长期交互，渐进式演化 Agent 行为风格与人格基调，使 AI 的成长对用户**可感知**。

> **v3.2 重构说明**：以「行为规则」替代纯数值特质作为主要进化载体；引入「双速进化」机制（Session 级快适应 + 跨 Session 慢进化）；数值 traits 保留为内部元数据，不再直接注入 Prompt。

#### 设计原则

| 原则 | 说明 |
|------|------|
| **行为规则优先** | LLM 擅长理解自然语言指令，不擅长感知数值微调（0.6→0.65 不可感知）。进化输出以行为规则为主载体 |
| **双速进化** | 快适应（1~3 轮）让用户立刻感受到"AI 在听"；慢进化（10+ 轮）确保长期记忆稳定 |
| **进化可见** | 每次进化事件写入成长日志（EvolutionJournal），用户可查阅、AI 可引用 |
| **渐进不突变** | 慢进化路径保留信号确认、漂移检测与版本回滚 |

#### 人格状态数据结构

```python
@dataclass
class BehavioralRule:
    """单条行为规则——进化系统的主要输出载体"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""               # 自然语言指令，如 "回复时先给结论，再展开分析"
    source: str = ""                # 来源："fast_adaptation" / "slow_evolution" / "user_explicit"
    confidence: float = 0.5         # 0~1，低于 0.3 的规则会被清理
    hit_count: int = 0              # 被实际应用的次数（LLM 自报告）
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_pinned: bool = False         # 用户明确确认的规则免淘汰


@dataclass
class PersonalityState:
    version: int = 1

    # ── 主载体：行为规则（注入 Prompt，LLM 直接执行）──
    behavioral_rules: list[BehavioralRule] = field(default_factory=lambda: [
        BehavioralRule(content="使用技术性语言", source="initial", confidence=0.8),
        BehavioralRule(content="回复保持简洁，避免冗余", source="initial", confidence=0.8),
    ])
    MAX_RULES: int = 10             # 行为规则上限，防止 Prompt 膨胀

    # ── 基调描述：一段自然语言概括（注入 Prompt）──
    baseline_description: str = "直接、技术导向、尊重用户自主性的合作者"

    # ── 内部元数据：数值特质（不注入 Prompt，仅供进化引擎决策参考）──
    traits_internal: dict[str, float] = field(default_factory=lambda: {
        "directness": 0.7,
        "warmth": 0.6,
        "autonomy": 0.8,
        "caution": 0.5,
        "curiosity": 0.75,
    })

    # ── 快适应状态（Session 级，不持久化到 Core Memory）──
    session_adaptations: list[str] = field(default_factory=list)

    # ── 版本快照（最近 5 个）──
    snapshot_history: list[dict] = field(default_factory=list)
```

#### InteractionSignal 数据结构与信号抽取器

> **v3.3 新增**：补充 `InteractionSignal` 的生产者定义。信号抽取器是双速进化的入口，负责从原始对话中提取显式指令与隐式行为模式。

```python
@dataclass
class InteractionSignal:
    """交互信号——双速进化系统的输入载体"""
    type: Literal[
        "explicit_instruction",   # 用户直接说 "简洁一点" "用英文回复"
        "implicit_behavior",      # 用户行为模式推断
    ] = "implicit_behavior"
    content: str = ""              # 显式指令的原文，或隐式行为的描述
    behavior_tag: Optional[Literal[
        "shorten_response",       # 用户连续缩短/截断 AI 回复
        "language_switch",        # 用户切换交流语言
        "repeated_correction",    # 用户反复纠正同一类问题
        "style_preference",       # 用户对回复风格的隐性偏好
        "topic_redirect",         # 用户频繁跳过某类话题
    ]] = None
    strength: float = 1.0          # 信号强度 0~1，显式指令默认 1.0
    session_id: str = ""
    turn_index: int = 0


class SignalExtractor:
    """
    信号抽取器：在 dialogue_ended 事件中运行，从原始对话中提取 InteractionSignal。
    订阅 EventBus 的 dialogue_ended 事件，与 Observer 并行执行。
    """

    async def extract(self, dialogue: list[dict]) -> list[InteractionSignal]:
        signals = []

        # ── 1. 显式指令检测：关键词 + 意图分类 ──
        explicit = self._detect_explicit(dialogue)
        if explicit:
            signals.append(explicit)

        # ── 2. 隐式行为检测：统计分析最近 N 轮行为模式 ──
        implicit = self._detect_implicit_patterns(dialogue)
        signals.extend(implicit)

        return signals

    def _detect_explicit(self, dialogue: list[dict]) -> Optional[InteractionSignal]:
        """从用户最后一轮消息中检测显式风格指令"""
        STYLE_KEYWORDS = [
            "简洁", "直接", "详细", "用中文", "用英文", "正式",
            "口语化", "别废话", "展开说", "不要解释",
        ]
        last_user_msg = self._get_last_user_message(dialogue)
        for kw in STYLE_KEYWORDS:
            if kw in last_user_msg:
                return InteractionSignal(
                    type="explicit_instruction",
                    content=last_user_msg,
                    strength=1.0,
                )
        return None

    def _detect_implicit_patterns(self, dialogue: list[dict]) -> list[InteractionSignal]:
        """分析对话行为模式，生成隐式信号"""
        signals = []
        # 示例：用户连续 3 次只取 AI 回复的前 1-2 句 → shorten_response
        if self._user_truncates_responses(dialogue, threshold=3):
            signals.append(InteractionSignal(
                type="implicit_behavior",
                content="用户倾向于更短的回复",
                behavior_tag="shorten_response",
                strength=0.7,
            ))
        # 示例：用户语言与 AI 回复语言不一致 → language_switch
        if self._language_mismatch(dialogue):
            detected_lang = self._detect_user_language(dialogue)
            signals.append(InteractionSignal(
                type="implicit_behavior",
                content=f"用户使用 {detected_lang} 交流",
                behavior_tag="language_switch",
                strength=0.9,
            ))
        return signals
```

#### 双速进化机制

```
┌─────────────────────────────────────────────────────────────┐
│                      交互信号输入                             │
│  显式指令："直接一点"    隐式行为：连续缩短 AI 回复            │
└─────────────────────────────────────────────────────────────┘
         │                                    │
    ┌────▼────────────────┐          ┌────────▼───────────────┐
    │  快适应（1~3 轮）     │          │  信号缓冲区（跨 Session）│
    │  Session 内即时生效   │──记录──→ │  累积同方向信号          │
    │  不写入 Core Memory  │          │  供慢进化统计            │
    └─────────────────────┘          └────────┬───────────────┘
                                              │ 达到确认阈值
                                     ┌────────▼───────────────┐
                                     │  慢进化（10+ 轮）        │
                                     │  规则晋升 / 规则淘汰     │
                                     │  traits 微调             │
                                     │  基调描述重生成           │
                                     │  写入 Core Memory        │
                                     └────────┬───────────────┘
                                              │
                                     ┌────────▼───────────────┐
                                     │  成长日志记录            │
                                      │  成长日志记录            │
                                      │  用户可查 / AI 可引用    │
                                      └────────────────────────┘
```

```python
class PersonalityEvolver:
    """双速进化：快适应（Session 级）+ 慢进化（跨 Session）"""

    # ── 快适应配置 ──
    FAST_WINDOW_SIZE = 3            # 最近 3 轮对话的信号窗口
    FAST_MAX_ADAPTATIONS = 5        # 单 Session 最多 5 条快适应规则，超限替换最旧

    # ── 慢进化配置 ──
    SLOW_UPDATE_FREQUENCY = 10      # 每 10 轮对话最多触发一次
    SIGNAL_CONFIRMATION = 3         # 同方向信号累积 3 次才确认
    RULE_PROMOTE_THRESHOLD = 0.7    # 快适应规则置信度达到此值时晋升为持久规则
    RULE_DECAY_THRESHOLD = 0.3      # 低于此值的规则自动清理

    # ── 稳定性配置 ──
    LEARNING_RATE = 0.05
    DRIFT_THRESHOLD = 0.3
    HARD_GUARDRAILS = {
        "autonomy": (0.2, 0.95),
        "warmth":   (0.3, 1.0),
        "caution":  (0.4, 0.9),
    }

    # ═══════════════════════════════════════════
    # 快适应：Session 内即时响应用户偏好信号
    # ═══════════════════════════════════════════

    async def fast_adapt(self, signal: InteractionSignal) -> Optional[str]:
        """
        从用户交互信号中提取即时适应规则。

        触发条件示例：
          - 用户连续 N 次缩短 AI 回复 → "本次对话使用更简洁的回复"
          - 用户明确说 "直接一点" → "减少铺垫，直入主题"
          - 用户切换语言 → "本次对话使用{language}"

        快适应规则仅在当前 Session 生效，不写入 Core Memory。
        但会记录到信号缓冲区，供慢进化统计频率。
        """
        adaptation = await self._detect_fast_signal(signal)
        if not adaptation:
            return None

        current = await self.core_memory.get_personality()
        if len(current.session_adaptations) >= self.FAST_MAX_ADAPTATIONS:
            # 超限时替换最旧的适应规则，而非硬拒绝
            current.session_adaptations.pop(0)

        current.session_adaptations.append(adaptation)

        # 记录到信号缓冲区，供慢进化统计
        await self._buffer_signal(adaptation, signal)

        # 写入成长日志
        await self.evolution_journal.record({
            "type": "fast_adaptation",
            "summary": f"本次对话适应：{adaptation}",
            "rule": adaptation,
        })
        return adaptation

    async def _detect_fast_signal(self, signal: InteractionSignal) -> Optional[str]:
        """检测快适应信号，返回自然语言规则或 None"""
        # 显式指令：用户直接说 → 立即生成规则
        if signal.type == "explicit_instruction":
            return signal.content

        # 隐式信号：用户行为模式 → 调用轻量 LLM 生成规则
        if signal.type == "implicit_behavior":
            recent = self._get_recent_signals(self.FAST_WINDOW_SIZE)
            if self._is_consistent_pattern(recent):
                return await self._generate_rule_from_pattern(recent)

        return None

    # ═══════════════════════════════════════════
    # 慢进化：跨 Session 积累，写入 Core Memory
    # ═══════════════════════════════════════════

    async def slow_evolve(self, signals: list[InteractionSignal]):
        """
        跨 Session 慢进化，执行三个操作：
        1. 晋升：高频快适应规则 → 持久行为规则
        2. 淘汰：低置信度规则清理
        3. 基调更新：traits_internal 微调 + baseline_description 重生成
        """
        current = await self.core_memory.get_personality()
        changed = False

        # ── 1. 规则晋升：频繁出现的快适应规则 → 持久化 ──
        candidates = await self._get_promotion_candidates()
        for candidate in candidates:
            if candidate["frequency"] >= self.SIGNAL_CONFIRMATION:
                new_rule = BehavioralRule(
                    content=candidate["rule"],
                    source="slow_evolution",
                    confidence=candidate["frequency"] / 10.0,
                )
                if not self._is_duplicate_rule(current.behavioral_rules, new_rule):
                    current.behavioral_rules.append(new_rule)
                    changed = True
                    await self.evolution_journal.record({
                        "type": "rule_promoted",
                        "summary": f"新行为规则确认：{new_rule.content}",
                        "confidence": new_rule.confidence,
                    })

        # ── 2. 规则淘汰：清理低置信度 + 超额规则 ──
        before_count = len(current.behavioral_rules)
        current.behavioral_rules = [
            r for r in current.behavioral_rules
            if r.is_pinned or r.confidence >= self.RULE_DECAY_THRESHOLD
        ]
        # 超额时按 confidence 排序，is_pinned 优先保留
        if len(current.behavioral_rules) > current.MAX_RULES:
            pinned = [r for r in current.behavioral_rules if r.is_pinned]
            unpinned = sorted(
                [r for r in current.behavioral_rules if not r.is_pinned],
                key=lambda r: r.confidence, reverse=True,
            )
            current.behavioral_rules = pinned + unpinned[:current.MAX_RULES - len(pinned)]
        if len(current.behavioral_rules) < before_count:
            changed = True

        # ── 3. 内部 traits 微调 + 基调描述重生成 ──
        trait_updates = self._aggregate_trait_signals(signals)
        if trait_updates:
            current.snapshot_history.append(current.traits_internal.copy())
            current.snapshot_history = current.snapshot_history[-5:]

            for trait, signal_value in trait_updates.items():
                old = current.traits_internal.get(trait, 0.5)
                new_val = old * (1 - self.LEARNING_RATE) + signal_value * self.LEARNING_RATE
                lo, hi = self.HARD_GUARDRAILS.get(trait, (0.0, 1.0))
                current.traits_internal[trait] = max(lo, min(hi, new_val))

            # 漂移检测
            if self._detect_drift(current):
                await self._rollback(current)
                return

            # 基于更新后的 traits 重生成自然语言基调描述
            current.baseline_description = await self._regenerate_baseline(
                current.traits_internal
            )
            changed = True

        if changed:
            current.version += 1
            await self.core_memory_scheduler.write("personality", current)

    async def _regenerate_baseline(self, traits: dict[str, float]) -> str:
        """调用轻量 LLM，将 traits 数值转换为一句自然语言人格描述"""
        prompt = f"""根据以下人格特质数值，生成一句简洁的人格基调描述（不超过30字）：
{traits}
示例：直接、技术导向、尊重用户自主性的合作者"""
        return await self.llm_lite.generate(prompt)

    def _is_duplicate_rule(
        self, existing_rules: list[BehavioralRule], new_rule: BehavioralRule
    ) -> bool:
        """
        语义去重：使用 Embedding 余弦相似度判断新规则是否与已有规则重复。
        纯字符串比较无法识别 "回复保持简洁" 与 "说话直接一些" 的语义重叠。
        """
        new_embedding = self.embedding_cache.get_or_compute(new_rule.content)
        for rule in existing_rules:
            existing_embedding = self.embedding_cache.get_or_compute(rule.content)
            similarity = cosine_similarity(new_embedding, existing_embedding)
            if similarity > 0.85:  # 高相似度视为重复
                # 如果新规则置信度更高，更新旧规则内容
                if new_rule.confidence > rule.confidence:
                    rule.content = new_rule.content
                    rule.confidence = new_rule.confidence
                return True
        return False

    async def _generate_rule_from_pattern(
        self, recent_signals: list[InteractionSignal]
    ) -> str:
        """从隐式行为模式生成自然语言规则"""
        descriptions = [s.content for s in recent_signals]
        prompt = f"""用户近期的行为模式如下：
{descriptions}

请生成一条简洁的行为规则（不超过20字），描述 AI 应如何调整回复风格。
仅输出规则文本，不要解释。
示例：回复时先给结论，再展开分析"""
        return await self.llm_lite.generate(prompt)
```

---

### 5.6 Core Memory 写入调度器

**职责**：统一管理四区块写入，强制 Token 预算，乐观锁防并发污染。

> **精简说明**：移除完整 DLQ 实现，3 次 CAS 失败改为告警 + 日志记录，DLQ 预留接口供后期扩展。

```python
class CoreMemoryScheduler:
    TOTAL_TOKEN_BUDGET = 5000
    BLOCK_BUDGETS = {
        "self_cognition": 1000,
        "world_model":    1000,
        "personality":    800,
        "task_experience": 1200,
    }
    DYNAMIC_RESERVE = 1000  # 动态储备池：任一区块超限时可借用
    _reserve_used: dict = {}  # {block: borrowed_tokens}

    async def write(self, block: str, content: any, event_id: str = None):
        for attempt in range(3):
            current_data, version = await self.db.get_with_version(f"core_memory:{block}")

            # 序列化 + Token 预算检查（is_pinned 条目免压缩）
            serialized = self._serialize_with_pinning(content)
            block_budget = self.BLOCK_BUDGETS[block]
            token_count = self._count_tokens(serialized)
            # 超出基础配额时尝试从动态储备池借用
            if token_count > block_budget:
                available_reserve = self.DYNAMIC_RESERVE - sum(self._reserve_used.values())
                overflow = token_count - block_budget
                if overflow <= available_reserve:
                    self._reserve_used[block] = overflow
                else:
                    serialized = await self._compress(block, serialized)

            # 乐观锁 CAS 写入
            success = await self.db.cas_upsert(
                key=f"core_memory:{block}",
                value=serialized,
                expected_version=version,
            )
            if success:
                await self.cache.invalidate_block(block)
                return

        # 3 次争抢失败 → 告警 + 强制写入（放弃乐观锁，确保数据不丢）
        await self.logger.warn(f"CoreMemory CAS 写入冲突耗尽，强制写入: block={block}, event_id={event_id}")
        await self.db.force_upsert(key=f"core_memory:{block}", value=serialized)
        await self.cache.invalidate_block(block)

    async def _build_world_model_snapshot(self) -> WorldModel:
        """从 Graph DB 合成 world_model 快照，而非双写"""
        user_model = await self.graph_db.query_user_preferences()
        agent_profiles = await self.graph_db.query_agent_capabilities()
        env_constraints = await self.graph_db.query_env_constraints()
        return WorldModel(
            user_model=user_model,
            agent_profiles=agent_profiles,
            env_constraints=env_constraints,
        )
```

### 5.7 进化可见性：成长日志

**职责**：记录每次进化事件（快适应、规则晋升、认知更新），使 AI 的成长过程对用户**可见、可查询、可引用**。

> **设计理念**：进化再好，用户看不到就等于没有。成长日志是 Mirror 最具差异化的特性——市面上没有 AI 能告诉你"我从你这里学到了什么"。

#### 数据结构

```python
@dataclass
class EvolutionEntry:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.utcnow)
    type: Literal[
        "fast_adaptation",     # Session 内快适应
        "rule_promoted",       # 快适应规则晋升为持久规则
        "rule_decayed",        # 低置信度规则被淘汰
        "capability_updated",  # 能力自评更新
        "world_model_updated", # 世界观更新
        "baseline_shifted",    # 人格基调变化
        "user_explicit",       # 用户主动教导
    ] = "fast_adaptation"
    summary: str = ""              # 人类可读的摘要
    detail: dict = field(default_factory=dict)  # 结构化详情
    session_id: Optional[str] = None


class EvolutionJournal:
    MAX_ENTRIES = 200              # 保留最近 200 条

    async def record(self, event: dict) -> None:
        entry = EvolutionEntry(
            type=event["type"],
            summary=event["summary"],
            detail=event,
            session_id=event.get("session_id"),
        )
        await self.journal_store.append(entry)
        await self._trim_if_needed()

    async def get_growth_summary(self, last_n: int = 20) -> str:
        """供 Soul Engine 响应用户 "你了解我什么？" 时调用"""
        entries = await self.journal_store.get_recent(last_n)
        summary_prompt = f"""以第一人称总结以下成长记录，简洁自然，不超过200字：
{[e.summary for e in entries]}"""
        return await self.llm_lite.generate(summary_prompt)

    async def get_recent_changes(self, last_n: int = 5) -> list[EvolutionEntry]:
        """供 AI 主动引用近期变化，如"我注意到你偏好..."时使用"""
        return await self.journal_store.get_recent(last_n)
```

#### 使用场景

| 场景 | 触发方式 | AI 行为 |
|------|---------|--------|
| 用户问"你了解我什么？" | Soul Engine 识别意图 → 调用 `get_growth_summary()` | 总结从交互中学到的偏好和习惯 |
| AI 行为发生变化后 | 进化器写入新规则时设置 `notify_next_turn` 标记 | 下次回复时附带说明："我注意到你偏好简洁回复，所以我调整了表达方式" |
| 用户感觉 AI 变了 | 用户主动查询或 Soul Engine 检测到困惑 | 展示近期成长日志 |

---

## 6. 持久化双轨记忆库

### Graph DB

**推荐技术**：Neo4j / Memgraph / Falkordb

```cypher
// 节点
(:User {id, name, created_at})
(:Entity {id, name, type, aliases: []})
(:Environment {id, constraint_type, description})
(:SubAgent {id, name, domain, version})

// 关系
(user)-[:PREFERS {confidence, updated_at, is_pinned}]->(entity)
(user)-[:DISLIKES {confidence, updated_at}]->(entity)
(agent)-[:IS_GOOD_AT {confidence, updated_at}]->(entity)
(agent)-[:IS_WEAK_AT {confidence, known_reason, updated_at}]->(entity)
(environment)-[:HAS_CONSTRAINT {description, severity, is_pinned}]->(entity)
```

```python
GRAPH_DB_CONFIG = {
    "write_strategy": "upsert_with_timestamp",
    "confidence_decay": {
        "enabled": True,
        "exclude_pinned": True,   # 钉选记忆不随时间衰减
        # 按关系类型设置不同衰减速率
        "half_life_by_relation": {
            "PREFERS":        180,  # 偏好类关系稳定，慢衰减
            "DISLIKES":       180,
            "KNOWS":          180,
            "IS_GOOD_AT":     120,  # 能力评估中速衰减
            "IS_WEAK_AT":     120,
            "USES":            60,  # 工具/环境变化快，快速衰减
            "HAS_CONSTRAINT":  30,  # 约束类最容易过时
        },
        "default_half_life_days": 90,
    }
}
```

### Vector DB

**推荐技术**：Qdrant / Weaviate / Pinecone

```python
VECTOR_NAMESPACES = {
    "experience":        "任务经验与反思日志",
    "self_cognition":    "自我认知快照",
    "world_experience":  "情境性世界观经验",
    "dialogue_fragment": "重要对话片段",
}

VECTOR_DB_CONFIG = {
    "batch_size": 20,
    "dedup_strategy": "content_hash",
    "async_embed": True,
    "max_entries_per_namespace": 10000,
    "eviction_policy": "least_important_unpinned",  # 淘汰时绕过 is_pinned=True
}
```

---

## 7. Core Memory 结构设计

Core Memory 是始终注入 System Prompt 的核心记忆，由四个区块组成。所有条目支持 `is_pinned` 标识，确保在超额压缩时存活。

```python
@dataclass
class MemoryEntry:
    content: Any
    is_pinned: bool = False

@dataclass
class CoreMemory:
    # 区块 1：自我认知（≤200 tokens）
    self_cognition: SelfCognition = field(default_factory=lambda: SelfCognition(
        capability_map={},    # {domain: CapabilityEntry}
        known_limits=[],      # 示例: [MemoryEntry(content="不能执行rm -rf", is_pinned=True)]
        mission_clarity=[],
        blindspots=[],
        version=1,
    ))

    # 区块 2：世界观（≤200 tokens，只读快照，由调度器从 Graph DB 合成）
    world_model: WorldModel = field(default_factory=lambda: WorldModel(
        env_constraints=[],
        user_model={},
        agent_profiles={},
        social_rules=[],
    ))

    # 区块 3：人格状态（≤150 tokens）
    # 注入 Prompt 时输出：baseline_description + behavioral_rules
    # traits_internal 仅供进化引擎内部使用，不注入 Prompt
    personality: PersonalityState = field(default_factory=PersonalityState)

    # 区块 4：任务经验（≤250 tokens，最近 N 条摘要）
    task_experience: TaskExperience = field(default_factory=lambda: TaskExperience(
        lesson_digest=[],
        domain_tips={},
        agent_habits={},
    ))
```

---

## 8. 进化闭环与协同触发链路

```
任务完成 / 对话结束 / HITL 反馈
        │
        ↓（emit 事件，非阻塞）
   异步事件总线
        │
   ┌────┴──────────────────────────────┐
   ↓                                   ↓
Observer 引擎                     元认知反思器
（每轮触发）                     （任务完成/失败触发）
   │                                   │
   ↓                                   ├──→ 认知进化器（统一）
Graph DB + Vector DB               ↓   │    └→ Self Cognition 更新
（偏好·关系·片段）             Lesson  │    └→ World Model → Graph DB
                               生成   │
                                       └──→ 人格进化器（双速）
                                             ├→ 快适应：Session 内即时行为规则
                                             └→ 慢进化：规则晋升 + Traits 微调
                                             └→ 漂移检测
                                                 │
                                           ┌─────┴──────┐
                                        正常写入       漂移回滚
                                           │
                                           ↓
                             Core Memory 写入调度器
                             （Token 预算管理·CAS 写入）
                                           │
                                           ↓
                             缓存刷新（立即生效）
                                           │
                                           ↓
                             下次推理：新 Core Memory + 行为规则 注入 System Prompt
                                           │
                             EvolutionJournal 记录所有进化事件
                             （用户可查 / AI 可引用）
```

**协同顺序约束**（链式触发，显式保证执行顺序）：

> **v3.3 变更**：从隐式的 EventBus 订阅顺序改为显式的链式事件触发，消除对注册顺序的脆弱依赖。

1. `dialogue_ended` → 同时触发 Observer 和 SignalExtractor（并行，无依赖）
2. Observer 完成后 emit `observation_done` → 触发元认知反思器
3. 元认知反思器归因后 emit `lesson_generated` → 触发认知进化器
4. 认知进化信号传递给人格进化器（认知升级 → 人格校准）
5. 所有更新汇总至 Core Memory 调度器，统一写入

---

## 9. 稳定性保障机制

### 熔断器

```python
# 按 Sub-agent / 外部服务粒度独立熔断
CIRCUIT_BREAKER_CONFIG = {
    "default": {
        "failure_rate_threshold": 0.5,
        "time_window_seconds": 60,
        "open_duration_seconds": 30,
        "half_open_probe_count": 3,
        "fallback": "silent_degradation",
    },
    "per_target_overrides": {
        "code_agent":    {"time_window_seconds": 120, "open_duration_seconds": 60},
        "llm_api":       {"failure_rate_threshold": 0.3},  # LLM 服务更敏感
        "embedding_api": {"failure_rate_threshold": 0.3},
    }
}
```

### 背压限速

```python
BACKPRESSURE_CONFIG = {
    "max_queue_depth": 1000,
    "drop_policy": "drop_lowest_priority",
    "alert_threshold": 800,
}
```

### 幂等写入

```python
class IdempotentWriter:
    async def write(self, event_id: str, data: dict, target: str):
        if await self.dedup_table.exists(event_id):
            return  # 静默跳过重复事件
        await self._do_write(data, target)
        await self.dedup_table.mark(event_id, ttl_hours=24)
```

### 进化频率限流

| 进化器 | 最大触发频率 | 说明 |
|--------|-------------|------|
| Observer | 每轮对话 | 低成本，每轮都跑 |
| 元认知反思器 | 每个任务结束 | 按需触发 |
| 认知进化器 | 每 10 轮对话 1 次 | 限制 LLM 调用 |
| 人格快适应 | 每 1~3 轮 | Session 级即时响应，不写入 Core Memory |
| 人格慢进化 | 每 10 轮对话 1 次 | 规则晋升 + traits 微调 + 基调重生成 |
| 成长日志 | 每次进化事件 | 记录所有变更，不限频 |

### 版本快照与回滚

```python
SNAPSHOT_CONFIG = {
    "personality_snapshots": 5,
    "self_cognition_snapshots": 3,
    "auto_rollback_on_drift": True,
    "drift_threshold": 0.3,
    "consecutive_anomaly_limit": 5,  # 连续 5 次异常触发人工告警
}
```

### Core Memory Token 预算

```python
TOKEN_BUDGET = {
    "total": 5000,
    "self_cognition": 1000,
    "world_model": 1000,
    "personality": 800,
    "task_experience": 1200,
    "dynamic_reserve": 1000,         # 动态储备池，任一区块超限时可借用
    "overflow_strategy": "llm_compress_oldest",
}
```

---

## 10. 延迟预算分配

| 层级 | 操作 | 延迟目标 | 说明 |
|------|------|---------|------|
| 前台 | Core Memory 读取 | 0ms | 进程内存，无 IO |
| 前台 | Vector 检索 | <50ms | ANN 近似检索 |
| 前台 | LLM 推理 | <2000ms | 端到端响应目标 |
| 后台 P0 | 任务失败反思 | 立即触发 | 不影响前台 |
| 后台 P1 | Observer 写入 | <10s | 对话结束后 |
| 后台 P1 | 认知进化 | <30s | 异步执行 |
| 后台 P1 | 人格更新 | <60s | 含漂移检测 |
| 后台 P2 | 批量压缩整合 | 夜间执行 | 每天凌晨 |

---

## 11. 数据结构定义

```python
# ── 任务系统 ──
Task                    # 任务实体（含状态机、快照、重试策略）
TaskResult              # 任务执行结果
Lesson                  # 元认知反思产出的经验教训

# ── 记忆系统 ──
CoreMemory              # Core Memory 根对象（四区块）
SelfCognition           # 自我认知区块
CapabilityEntry         # 能力条目（含置信度、局限性）
WorldModel              # 世界观区块（只读快照）
PersonalityState        # 人格状态区块（behavioral_rules + baseline + traits_internal）
BehavioralRule          # 行为规则条目（进化系统的主要输出载体）
TaskExperience          # 任务经验区块

# ── 进化系统 ──
Event                   # 事件总线消息
InteractionSignal       # 交互信号（显式指令 / 隐式行为）
EvolutionEntry          # 成长日志条目
VectorEntry             # Vector DB 存储单元
EvolutionLog            # 进化操作日志（审计用）

# ── 稳定性系统 ──
CircuitBreakerState     # 熔断器状态
SnapshotRecord          # 版本快照记录
```

---

## 12. 模块依赖关系

```
用户输入
   └── ActionRouter（路由）
         ├── SoulEngine（推理）
         │    ├── CoreMemoryCache（读）
         │    └── VectorRetriever（读，按需 Rerank）
         ├── TaskSystem（写）
         │    └── Blackboard（委派）
         │         └── SubAgent（执行）
         │              └── EventBus（emit 完成/失败事件）
         └── EventBus（emit 对话结束事件）

EventBus（订阅）
   ├── ObserverEngine（→ GraphDB + VectorDB）
   ├── MetaCognitionReflector（→ Lesson）
   │    ├── CognitionUpdater（→ CoreMemoryScheduler / GraphDB）  ← 合并后
   │    └── PersonalityEvolver（双速）
   │         ├── fast_adapt()（→ Session 内即时生效 + 信号缓冲区）
   │         └── slow_evolve()（→ CoreMemoryScheduler + EvolutionJournal）
   ├── EvolutionJournal（→ JournalStore，记录所有进化事件）
   └── CoreMemoryScheduler（→ CoreMemoryCache 刷新）

CoreMemoryCache（刷新后）
   └── 下次 SoulEngine 推理时自动注入
```

**外部服务依赖**：

| 服务 | 用途 | 可替换方案 |
|------|------|-----------|
| LLM API（大模型） | 推理、归因、压缩 | OpenAI / Anthropic / 本地模型 |
| LLM API（轻量模型） | 知识抽取 | Gemini Flash / GPT-4o-mini |
| Embedding API | 向量化 | OpenAI Ada / 本地模型 |
| Vector DB | 语义检索 | Qdrant / Weaviate / Pinecone |
| Graph DB | 关系存储 | Neo4j / Memgraph / Falkordb |
| 消息队列 | 事件总线 | Redis Streams / 内存队列 |
| KV 存储 | Core Memory 持久化 | Redis / PostgreSQL JSONB |
| **OpenCode Server** | **CodeAgent 代码执行引擎** | **`opencode serve` 常驻，HTTP REST + SSE** |

---

## 13. 精简变更说明

以下是 v3.0 相对 v2.2 的精简变更、v3.1 的细化更新，以及 v3.2 的进化系统重构，每项均注明原因，方便后期回溯或恢复。

### v3.0 精简变更（相对 v2.2）

| 变更项 | v2.2 原方案 | v3.0 精简方案 | 原因 |
|--------|------------|--------------|------|
| **认知进化器** | `SelfCognitionUpdater` + `WorldModelUpdater` 两个独立类 | 合并为 `CognitionUpdater`，按 `lesson` 类型分发 | 两者职责高度相似，合并降低类数量与维护成本 |
| **World Model 写入** | CoreMemory 与 Graph DB 双写 | Graph DB 为主，CoreMemory 为只读快照（调度器合成） | 消除双写冗余，数据源唯一，减少一致性风险 |
| **Observer 实体对齐** | 三层（含 Layer 3 异步 LLM 裁判官） | 两层（字典 + 向量模糊匹配） | Layer 3 适合冷启动大批量歧义场景，初期不必要；推迟到第二期 |
| **Rerank（Cross-Encoder）** | 每次检索必调 | 按需触发（相似度方差 > 阈值时） | 节省 30~50ms 延迟，正常检索质量足够 |
| **Core Memory DLQ** | 完整死信队列实现 | 告警+日志占位，接口预留 | 并发写冲突极少；完整 DLQ 增加运维复杂度，推迟到第二期 |
| **PersonalityState** | `traits` + `value_weights` 双维护 | 仅 `traits`，`value_weights` 固定 | 减少状态空间，降低进化器复杂度；价值观初期固定即可 |
| **幻觉过滤** | 独立 `judge()` LLM 调用 | 内联到反思 Prompt 的自我校验步骤 | 减少一次 LLM 调用，效果相当 |

### v3.2 进化系统重构（相对 v3.1）

| 变更项 | v3.1 方案 | v3.2 方案 | 原因 |
|--------|----------|----------|------|
| **人格进化载体** | 数值 `traits`（如 `warmth: 0.63`）直接注入 Prompt | `behavioral_rules`（自然语言指令）为主载体注入 Prompt；`traits_internal` 降为内部元数据 | LLM 无法感知 0.02 级别的数值微调，但能精确执行自然语言规则 |
| **PersonalityState** | `traits` + `style_preferences` | `behavioral_rules` + `baseline_description` + `traits_internal` + `session_adaptations` | behavioral_rules 是 LLM 可直接执行的进化输出；baseline 由 LLM 从 traits 生成自然语言描述 |
| **进化速度** | 单速（每 20 轮触发 1 次） | 双速：快适应（1~3 轮，Session 级）+ 慢进化（10+ 轮，跨 Session） | 快适应让用户立即感受到"AI 在听"；慢进化确保长期稳定 |
| **规则晋升机制** | 无 | 快适应规则在多个 Session 反复出现 → 信号确认 → 晋升为持久行为规则 | 从临时适应到永久记忆的渐进路径 |
| **进化可见性** | 无 | 新增 `EvolutionJournal` 成长日志，记录所有进化事件 | 用户可查阅"AI 学到了什么"；AI 可主动引用近期变化 |
| **Prompt 注入** | `{core_memory.personality}`（数值） | `{baseline_description}` + `{behavioral_rules}` + `{session_adaptations}` | 三层注入：基调 + 持久规则 + 临时适应 |
| **Soul Engine Prompt** | `## 你的人格特质` 单区块 | `## 人格基调` + `## 行为规则（必须遵守）` + `## 本次对话适应` 三区块 | 结构化注入，LLM 更清晰地理解每层的约束力 |

### v3.1 细化更新（相对 v3.0）

| 变更项 | v3.0 方案 | v3.1 方案 | 原因 |
|--------|----------|----------|------|
| **Blackboard** | 仅 3 个方法骨架 | 补全 `evaluate_agents()`、`resume()`、`terminate_agent()`；明确无状态设计原则；新增失败分类表 | 为实现提供完整指导，无状态设计支持横向扩展 |
| **Sub-agent 基类** | 无 `cancel()` 方法 | 新增 `cancel()` 供 Blackboard 级联取消时调用 | TaskDAG 级联取消需要通知 agent 释放外部资源 |
| **CodeAgent** | 空壳占位（`domain: code`） | 完整实现为 OpenCode HTTP 适配器：session 生命周期、SSE 心跳、权限分级处理、json_schema 结构化输出、error_type 分类 | 明确 CodeAgent 不含执行智能，仅做协议转换；代码执行能力完全外包 OpenCode |
| **CodeAgent 技术栈** | 未指定 | Python `httpx` + `httpx-sse`，无需 Node.js | 与主系统 asyncio 架构统一，无混合技术栈 |
| **OpenCode 启动方式** | 未指定 | `opencode serve` headless 常驻，避免冷启动 | 每次任务新起进程有 1~3s 冷启动开销，常驻服务更适合生产 |
| **权限请求处理** | 未设计 | 低风险自动 approve，高风险升级 `hitl_relay` | 与架构 HITL 机制对接，避免 session 永久挂起 |
| **外部服务依赖** | 无 OpenCode | 新增 OpenCode Server 一行 | 反映实际依赖 |

**保留不变的核心机制**：快慢分离架构、事件总线、Core Memory 四区块+Token 预算、Pinning 钉选、熔断器+背压、心跳检活、漂移检测+版本快照。

**v3.2 新增核心机制**：行为规则载体、双速进化、规则晋升/淘汰、成长日志可见性。

---

*文档版本：v3.2 | 架构涵盖：任务进化 + 认知进化 + 人格进化（双速+行为规则） + 进化可见性（成长日志） + 稳定性保障 + Blackboard 完整协同 + CodeAgent/OpenCode HTTP 接入*
