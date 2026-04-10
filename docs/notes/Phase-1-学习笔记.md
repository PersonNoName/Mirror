# Phase 1 学习笔记：解耦接口层

> **前置阶段**：[[Phase-0-学习笔记]]  
> **目标**：定义全项目共用的数据结构和解耦边界的抽象接口（ABC）  
> **重要**：本阶段**只写接口，不写实现**

---

## 目录

- [概述](#概述)
- [1. Platform 接口](#1-platform-接口)
- [2. Model Provider 接口](#2-model-provider-接口)
- [3. SubAgent 接口](#3-subagent-接口)
- [4. Task 数据结构](#4-task-数据结构)
- [5. Outbox 数据结构](#5-outbox-数据结构)
- [6. Core Memory 数据结构](#6-core-memory-数据结构)
- [7. Event 数据结构](#7-event-数据结构)
- [8. 注册表骨架](#8-注册表骨架)
- [9. 验收标准](#9-验收标准)
- [10. 关键设计原则](#10-关键设计原则)

---

## 概述

### 目标

Phase 1 的目标是**定义接口，不写实现**。通过抽象基类（ABC）和数据类（Pydantic）建立解耦边界，确保后续 Phase 实现时不违反架构原则。

### 核心原则

- **依赖倒置**：高层模块不依赖低层模块，而是依赖抽象
- **接口隔离**：每个接口只做一件事
- **无循环依赖**：接口定义文件中不 import 其他接口文件的具体类

### Phase 1 文件清单

| 文件 | 内容 |
|------|------|
| `app/platform/base.py` | Platform 接口与数据类型 |
| `app/providers/base.py` | Model Provider 接口与数据类型 |
| `app/agents/base.py` | SubAgent 抽象基类 |
| `app/tasks/models.py` | Task 相关数据类 |
| `app/infra/outbox.py` | OutboxEvent 数据类 |
| `app/memory/core_memory.py` | Core Memory 数据结构 |
| `app/evolution/event_bus.py` | Event 总线接口与数据类型 |
| `app/tools/registry.py` | ToolRegistry 骨架 |
| `app/hooks/registry.py` | HookRegistry 骨架 |

---

## 1. Platform 接口

### 1.1 职责

Platform 接口层负责：
- **接收**用户消息（normalize_inbound）
- **发送**回复给用户（send_outbound）
- **发送** HITL（Human-In-The-Loop）请求（send_hitl）

### 1.2 数据类型

#### PlatformContext（平台上下文）

携带当前会话的平台相关信息，如：
- `user_id`：用户 ID
- `session_id`：会话 ID
- `capabilities`：平台能力（是否支持 SSE 流式等）
- `metadata`：平台特定元数据

#### InboundMessage（入站消息）

```python
class InboundMessage(BaseModel):
    user_id: str
    session_id: str
    text: str                          # 用户原始消息
    message_id: str | None = None      # 平台消息 ID（用于去重）
    timestamp: datetime | None = None
    metadata: dict[str, Any] = {}
```

#### OutboundMessage（出站消息）

```python
class OutboundMessage(BaseModel):
    session_id: str
    text: str                          # 回复文本
    stream: bool = False               # 是否为流式
    metadata: dict[str, Any] = {}
```

#### HitlRequest（HITL 请求）

```python
class HitlRequest(BaseModel):
    session_id: str
    question: str                      # 向用户确认的问题
    context: dict[str, Any] = {}       # 上下文信息
    timeout: int = 300                  # 等待用户响应的超时时间（秒）
```

### 1.3 抽象基类

```python
class PlatformAdapter(ABC):
    """平台适配器抽象基类"""
    
    @abstractmethod
    async def normalize_inbound(self, raw: Any) -> InboundMessage:
        """将平台原始消息转换为标准 InboundMessage"""
        ...
    
    @abstractmethod
    async def send_outbound(self, message: OutboundMessage) -> None:
        """发送回复消息给用户"""
        ...
    
    @abstractmethod
    async def send_hitl(self, request: HitlRequest) -> None:
        """发送 HITL 请求给用户"""
        ...
```

### 1.4 设计意图

```
用户消息（Web/Telegram/Discord...）
    ↓
PlatformAdapter.normalize_inbound()
    ↓
标准 InboundMessage
    ↓
Soul Engine（后续 Phase）
    ↓
PlatformAdapter.send_outbound() / send_hitl()
    ↓
用户（同一平台）
```

**好处**：接入新平台只需实现新的 PlatformAdapter，不影响核心逻辑。

---

## 2. Model Provider 接口

### 2.1 职责

Model Provider 接口层负责：
- 统一管理所有 LLM / Embedding / Reranker 调用
- 屏蔽不同模型供应商的 SDK 差异
- 支持 `provider_type`（协议族）和 `vendor`（实际供应商）分离

### 2.2 数据类型

#### ModelSpec（模型规格）

```python
class ModelSpec(BaseModel):
    profile: str              # 配置 profile 名，如 "reasoning.main"
    capability: str           # 能力类型：chat / embedding / reranker
    provider_type: str        # 协议族：openai_compatible / ollama / native
    vendor: str               # 实际供应商：openai / minimax / local
    model: str                # 模型名：gpt-4.1 / gpt-4.1-mini
    base_url: str             # API 端点
    api_key: str = ""
```

**关键设计**：`provider_type` 和 `vendor` 分离，允许同一个协议指向不同供应商。

### 2.3 抽象基类

#### ChatModel（对话模型）

```python
class ChatModel(ABC):
    """对话模型抽象基类"""
    
    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        **kwargs
    ) -> ChatResponse:
        """同步生成"""
        ...
    
    @abstractmethod
    async def stream(
        self,
        messages: list[ChatMessage],
        **kwargs
    ) -> AsyncGenerator[ChatDelta, None]:
        """流式生成"""
        ...
```

#### EmbeddingModel（嵌入模型）

```python
class EmbeddingModel(ABC):
    """嵌入模型抽象基类"""
    
    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        **kwargs
    ) -> list[list[float]]:
        """批量生成嵌入向量"""
        ...
```

#### RerankerModel（重排序模型）

```python
class RerankerModel(ABC):
    """重排序模型抽象基类"""
    
    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 10,
        **kwargs
    ) -> list[RerankResult]:
        """对文档重排序"""
        ...
```

### 2.4 配置 profile

| Profile | 用途 |
|---------|------|
| `reasoning.main` | 主要推理模型（GPT-4.1） |
| `lite.extraction` | 轻量提取模型（GPT-4.1-mini） |
| `retrieval.embedding` | 嵌入模型（text-embedding-3-large） |
| `retrieval.reranker` | 本地重排序服务 |

### 2.5 设计意图

```
业务代码
    ↓
ModelProviderRegistry.get("reasoning.main")
    ↓
具体 ChatModel 实现（如 OpenAICompatibleChatModel）
    ↓
httpx 调用实际 API
```

**好处**：切换模型供应商只需修改配置，不改代码。

---

## 3. SubAgent 接口

### 3.1 职责

SubAgent 是任务执行层的执行单元，由 Blackboard 统一调度。

### 3.2 抽象基类

```python
class SubAgent(ABC):
    """SubAgent 抽象基类"""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent 名称"""
        ...
    
    @abstractmethod
    async def execute(self, task: Task) -> TaskResult:
        """执行任务（核心方法）"""
        ...
    
    @abstractmethod
    def estimate_capability(self, task: Task) -> float:
        """
        评估 Agent 对任务的适配度
        
        要求：
        - 轻量：< 10ms
        - 无网络调用
        - 返回 0.0 ~ 1.0 的置信度
        """
        ...
    
    @abstractmethod
    async def resume(self, task: Task, resume_data: dict[str, Any]) -> TaskResult:
        """恢复暂停的任务"""
        ...
    
    @abstractmethod
    async def cancel(self, task: Task) -> None:
        """取消任务"""
        ...
    
    @abstractmethod
    def emit_heartbeat(self, task_id: str) -> None:
        """发送心跳（更新 Task 最后活跃时间）"""
        ...
```

### 3.3 设计意图

```
Blackboard
    ↓
for agent in AgentRegistry.all():
    score = agent.estimate_capability(task)  # 快速评分
    ↓
best_agent = max(agents, key=lambda a: score)
    ↓
blackboard.assign(best_agent, task)
    ↓
agent.execute(task)
    ↓
返回 TaskResult
```

### 3.4 estimate_capability 设计原则

`estimate_capability` 必须：
- **轻量**（< 10ms）：不能有网络调用或复杂计算
- **无副作用**：只读不写
- **快速过滤**：用于选择最优 Agent，不是精确判断

常用实现方式：
- 关键词匹配
- 任务类型枚举
- 简单规则表

---

## 4. Task 数据结构

### 4.1 Task（任务）

```python
class Task(BaseModel):
    id: UUID
    user_id: str
    session_id: str
    status: TaskStatus
    task_type: str                      # 任务类型（如 "code", "web_search"）
    prompt: str                        # 任务描述
    dispatch_stream: str | None = None  # Redis Stream 名称
    consumer_group: str | None = None   # Consumer Group
    delivery_token: str | None = None   # Redis Streams delivery token
    result: TaskResult | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    metadata: dict[str, Any] = {}
```

### 4.2 TaskStatus（任务状态枚举）

```python
class TaskStatus(str, Enum):
    PENDING = "pending"                 # 等待调度
    RUNNING = "running"                 # 执行中
    WAITING_HITL = "waiting_hitl"       # 等待人工介入
    COMPLETED = "completed"             # 已完成
    FAILED = "failed"                   # 失败
    CANCELLED = "cancelled"             # 已取消
```

### 4.3 TaskResult（任务结果）

```python
class TaskResult(BaseModel):
    success: bool
    output: str | None = None           # 结构化输出
    error: str | None = None
    metadata: dict[str, Any] = {}
```

### 4.4 Lesson（经验教训）

从任务执行中提取的经验教训，用于进化：

```python
class Lesson(BaseModel):
    id: UUID
    task_id: UUID
    type: str                            # "success" / "failure" / "improvement"
    summary: str                         # 简要总结
    detail: str                          # 详细描述
    confidence: float                    # 置信度 0.0 ~ 1.0
    created_at: datetime
```

### 4.5 Redis Streams 相关字段

| 字段 | 用途 |
|------|------|
| `dispatch_stream` | 任务派发到的 Stream（如 `stream:task:dispatch`） |
| `consumer_group` | Consumer Group（如 `code-agent-workers`） |
| `delivery_token` | Redis Streams 的 delivery token，用于 ACK |

---

## 5. Outbox 数据结构

### 5.1 OutboxEvent

```python
class OutboxEvent(BaseModel):
    id: UUID
    topic: str                           # 消息主题/队列名
    payload: dict[str, Any]              # 消息内容
    status: OutboxEventStatus            # pending / published / failed
    retry_count: int = 0
    next_retry_at: datetime | None = None
    created_at: datetime
    published_at: datetime | None = None
```

### 5.2 OutboxEventStatus

```python
class OutboxEventStatus(str, Enum):
    PENDING = "pending"
    PUBLISHED = "published"
    FAILED = "failed"
```

### 5.3 与 Phase 0 数据库表的对应

| OutboxEvent 字段 | outbox_events 表字段 |
|-----------------|---------------------|
| `id` | `id` (PK) |
| `topic` | `topic` |
| `payload` | `payload` (JSONB) |
| `status` | `status` |
| `retry_count` | `retry_count` |
| `next_retry_at` | `next_retry_at` |
| `created_at` | `created_at` |
| `published_at` | `published_at` |

---

## 6. Core Memory 数据结构

### 6.1 CoreMemory（核心记忆）

Core Memory 是 AI Agent 的核心认知结构，分为四个区块：

```python
class CoreMemory(BaseModel):
    user_id: str
    version: int
    self_cognition: SelfCognition        # 自我认知
    world_model: WorldModel              # 世界模型
    personality_state: PersonalityState  # 人格状态
    task_experience: TaskExperience      # 任务经验
    updated_at: datetime
```

### 6.2 SelfCognition（自我认知）

```python
class SelfCognition(BaseModel):
    name: str                            # AI 名称
    identity: str                         # 身份定义
    capabilities: list[str]               # 能力列表
    limitations: list[str]                # 能力边界
    baseline_description: str             # 基线描述（用于 System Prompt）
```

### 6.3 WorldModel（世界模型）

```python
class WorldModel(BaseModel):
    user_preferences: list[str]           # 用户偏好
    user_dislikes: list[str]             # 用户厌恶
    environmental_constraints: list[str]  # 环境约束
    summary: str                          # 自然语言摘要（由 GraphStore 生成）
```

### 6.4 PersonalityState（人格状态）

```python
class PersonalityState(BaseModel):
    traits: dict[str, float]             # 人格特质（数值）
    behavioral_rules: list[BehavioralRule]  # 行为规则
    recent_adaptations: list[str]         # 最近适应（session 内）
    slow_evolution_signals: list[str]    # 慢进化信号累积
```

### 6.5 BehavioralRule（行为规则）

```python
class BehavioralRule(BaseModel):
    id: UUID
    rule_type: str                        # "session" / "slow"
    content: str                          # 规则内容
    trigger: str                          # 触发条件
    confidence: float                     # 置信度
    created_at: datetime
    updated_at: datetime
```

### 6.6 TaskExperience（任务经验）

```python
class TaskExperience(BaseModel):
    successful_tasks: list[str]           # 成功任务类型
    failed_tasks: list[str]              # 失败任务类型
    lessons: list[UUID]                   # Lesson IDs
    skill_mastery: dict[str, float]      # 技能掌握度
```

### 6.7 持久化策略

```
Core Memory
    ↓ 快照
PostgreSQL (core_memory_snapshots)
    ↓ 缓存
Redis (热副本，可选)
    ↓ 失效广播
CoreMemoryCache.invalidate(user_id)
```

---

## 7. Event 数据结构

### 7.1 EventType（事件类型，8 种）

```python
class EventType(str, Enum):
    DIALOGUE_ENDED = "dialogue_ended"           # 对话结束
    TASK_COMPLETED = "task_completed"           # 任务完成
    TASK_FAILED = "task_failed"                 # 任务失败
    OBSERVATION_DONE = "observation_done"       # 观察完成
    LESSON_GENERATED = "lesson_generated"       # 经验生成
    COGNITION_UPDATED = "cognition_updated"     # 认知更新
    PERSONALITY_EVOLVED = "personality_evolved" # 人格进化
    LOW_PRIORITY = "low_priority"               # 低优先级事件
```

### 7.2 Event（事件）

```python
class Event(BaseModel):
    id: UUID
    type: EventType
    user_id: str
    session_id: str | None = None
    payload: dict[str, Any]                     # 事件数据
    priority: int = 0                           # 优先级（0 为最低）
    stream_name: str | None = None              # Redis Stream 名称
    delivery_id: str | None = None              # 投递 ID
    created_at: datetime
```

### 7.3 InteractionSignal（交互信号）

从对话中提取的用户信号：

```python
class InteractionSignal(BaseModel):
    type: str                    # "preference" / "dislike" / "correction" / "praise"
    content: str                  # 信号内容
    explicit: bool               # 是否显式（vs 隐式行为）
    confidence: float            # 置信度
```

### 7.4 EvolutionEntry（进化条目）

记录每次进化操作：

```python
class EvolutionEntry(BaseModel):
    id: UUID
    user_id: str
    trigger: str                 # 触发原因
    changes: dict[str, Any]      # 变更内容
    snapshot_before: str | None  # 变更前快照（JSON）
    snapshot_after: str | None   # 变更后快照（JSON）
    created_at: datetime
```

### 7.5 Event → Redis Streams 映射

| EventType | Stream Name |
|-----------|-------------|
| DIALOGUE_ENDED | `stream:event:dialogue` |
| TASK_COMPLETED / TASK_FAILED | `stream:event:task_result` |
| OBSERVATION_DONE / LESSON_GENERATED / COGNITION_UPDATED / PERSONALITY_EVOLVED | `stream:event:evolution` |
| LOW_PRIORITY | `stream:event:low_priority` |

---

## 8. 注册表骨架

### 8.1 ToolRegistry（工具注册表）

```python
class ToolRegistry:
    """工具注册表（全局单例）"""
    
    def register(
        self,
        name: str,
        description: str,
        schema: dict[str, Any]
    ) -> Callable:
        """装饰器注册"""
        ...
    
    def get(self, name: str) -> Tool | None:
        """获取工具"""
        ...
    
    def all(self) -> list[Tool]:
        """列出所有工具"""
        ...
    
    def unregister(self, name: str) -> None:
        """取消注册"""
        ...
```

### 8.2 HookRegistry（钩子注册表）

```python
class HookPoint(str, Enum):
    PRE_REASON = "pre_reason"      # LLM 推理前
    POST_REASON = "post_reason"    # LLM 推理后
    PRE_TASK = "pre_task"          # 任务执行前
    POST_REPLY = "post_reply"      # 回复发送前

class HookRegistry:
    """钩子注册表（全局单例）"""
    
    def register(
        self,
        point: HookPoint,
        handler: Callable[[HookContext], Any]
    ) -> None:
        ...
    
    async def execute(self, point: HookPoint, context: HookContext) -> None:
        """
        执行指定插入点的所有钩子
        
        重要：任何异常只记录日志，不中断主流程
        """
        ...
```

### 8.3 HookContext（钩子上下文）

```python
class HookContext(BaseModel):
    point: HookPoint
    user_id: str
    session_id: str
    data: dict[str, Any]  # 传递的数据（不同插入点内容不同）
```

---

## 9. 验收标准

### 9.1 验收命令

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
```

### 9.2 验收检查项

- [ ] 无 `ImportError`
- [ ] 无循环导入
- [ ] 所有抽象基类方法签名正确
- [ ] 所有数据类字段类型正确
- [ ] `tool_registry` 全局单例可访问
- [ ] `HookRegistry` 全局单例可访问

---

## 10. 关键设计原则

### 10.1 接口与实现分离

```
抽象接口（ABC）          具体实现
─────────────────        ─────────────────
PlatformAdapter    →     WebPlatformAdapter
ChatModel          →     OpenAICompatibleChatModel
SubAgent           →     CodeAgent / WebAgent
ToolRegistry       →     ToolRegistryImpl
```

### 10.2 依赖倒置示例

```python
# 错误示范（直接依赖实现）
from app.agents.code_agent import CodeAgent

# 正确做法（依赖抽象）
from app.agents.base import SubAgent
agent: SubAgent = agent_registry.get("code_agent")
```

### 10.3 无循环依赖的 import 结构

```
app/platform/base.py      # 只定义接口，不 import 其他接口文件
app/providers/base.py      # 只定义接口，不 import 其他接口文件
app/agents/base.py        # 只定义接口，不 import 其他接口文件
app/tasks/models.py        # 只定义数据类，不 import 接口
app/memory/core_memory.py  # 只定义数据类，不 import 接口
app/evolution/event_bus.py # 只定义接口和数据类
app/tools/registry.py      # 只定义注册表
app/hooks/registry.py      # 只定义注册表
```

### 10.4 Hook 执行保证

```python
async def execute(self, point: HookPoint, context: HookContext) -> None:
    for handler in self._handlers[point]:
        try:
            await handler(context)
        except Exception as e:
            logger.warning("hook_execution_failed", point=point, error=e)
            # 不 re-raise，继续执行下一个 handler
```

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-0-学习笔记]] — Phase 0 学习笔记
- [[Phase-2-学习笔记|Phase 2]] — Model Provider 实现（待完成）
