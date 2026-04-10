# Phase 3 学习笔记：记忆系统

> **前置阶段**：[[Phase-2-学习笔记]]  
> **目标**：实现向量检索、图存储、Core Memory 持久化，使记忆的读写可以正常工作

---

## 目录

- [概述](#概述)
- [1. 存储架构](#1-存储架构)
- [2. Core Memory 数据结构](#2-core-memory-数据结构)
- [3. Core Memory 存储](#3-core-memory-存储)
- [4. Core Memory 缓存](#4-core-memory-缓存)
- [5. Session 上下文缓存](#5-session-上下文缓存)
- [6. Vector 检索](#6-vector-检索)
- [7. Graph 存储](#7-graph-存储)
- [8. 验收标准](#8-验收标准)
- [9. 与 Phase 1 接口的对应](#9-与-phase-1-接口的对应)

---

## 概述

### 目标

Phase 3 的目标是**实现记忆系统**，使 AI Agent 具备：
- 长期记忆的持久化和检索
- 语义向量检索
- 关系图谱存储
- Session 级别的上下文缓存

### Phase 3 文件清单

| 文件 | 内容 |
|------|------|
| `app/memory/core_memory.py` | CoreMemory 数据结构和缓存 |
| `app/memory/core_memory_store.py` | PostgreSQL 持久化存储 |
| `app/memory/session_context.py` | Redis Session 上下文存储 |
| `app/memory/vector_retriever.py` | Qdrant 向量检索 |
| `app/memory/graph_store.py` | Neo4j 图存储 |
| `migrations/002_phase3_memory.sql` | PostgreSQL schema |

---

## 1. 存储架构

### 1.1 四类存储的职责分层

```
┌─────────────────────────────────────────────────────────┐
│                    Core Memory Cache                     │
│              (进程内，per-user，懒加载)                   │
└─────────────────────────────────────────────────────────┘
         ↑ invalidate()                    ↓ _publish_invalidation()
┌─────────────────────┐         ┌─────────────────────────┐
│  PostgreSQL         │         │  Redis                  │
│  (持久化真相源)       │         │  (Session 上下文 + 失效广播) │
│  core_memory_snapshots│       │  session_ctx:*           │
└─────────────────────┘         └─────────────────────────┘
         ↑                              ↓
┌─────────────────────┐         ┌─────────────────────────┐
│  Qdrant             │         │  Neo4j                   │
│  (向量语义检索)       │         │  (关系图谱)              │
│  mirror_memory       │         │  MemoryEntity            │
└─────────────────────┘         └─────────────────────────┘
```

### 1.2 存储职责表

| 存储 | 职责 | 数据类型 |
|------|------|---------|
| **PostgreSQL** | Core Memory 持久化真相源 | 四个区块的 JSONB 快照 |
| **Redis** | Session 上下文、会话适应、失效广播 | 最近 N 条消息、适应状态 |
| **Qdrant** | 语义向量检索 | 情境经验、对话片段 |
| **Neo4j** | 长期关系图谱 | 用户偏好、厌恶、能力判断 |

### 1.3 关键设计原则

- **PostgreSQL 是真相源**：Core Memory 快照必须以 PostgreSQL 为准
- **Redis 是可选缓存**：Session 上下文不进入长期真相存储
- **Qdrant 只存语义数据**：不存规则真相和任务真相
- **Neo4j 只写稳定关系**：不存运行时状态

---

## 2. Core Memory 数据结构

### 2.1 四个区块

```python
@dataclass(slots=True)
class CoreMemory:
    """Per-user core memory composed of four durable prompt blocks."""

    self_cognition: SelfCognition      # 自我认知
    world_model: WorldModel            # 世界模型
    personality: PersonalityState      # 人格状态
    task_experience: TaskExperience    # 任务经验
```

### 2.2 SelfCognition（自我认知）

```python
@dataclass(slots=True)
class SelfCognition:
    capability_map: dict[str, CapabilityEntry]  # 能力列表
    known_limits: list[MemoryEntry]             # 已知限制
    mission_clarity: list[MemoryEntry]          # 使命澄清
    blindspots: list[MemoryEntry]               # 盲点
    version: int = 1

@dataclass(slots=True)
class CapabilityEntry:
    description: str
    confidence: float = 0.0
    limitations: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 2.3 WorldModel（世界模型）

```python
@dataclass(slots=True)
class WorldModel:
    env_constraints: list[MemoryEntry]        # 环境约束
    user_model: dict[str, MemoryEntry]        # 用户模型
    agent_profiles: dict[str, MemoryEntry]    # Agent profiles
    social_rules: list[MemoryEntry]           # 社交规则
```

### 2.4 PersonalityState（人格状态）

```python
@dataclass(slots=True)
class PersonalityState:
    baseline_description: str = ""             # 基线描述
    behavioral_rules: list[BehavioralRule]     # 行为规则
    traits_internal: dict[str, float]         # 内部特质
    session_adaptations: list[str]            # Session 适应

@dataclass(slots=True)
class BehavioralRule:
    rule: str                                # 规则内容
    rationale: str = ""                       # 理由
    priority: int = 1
    source: str = "system"
    confidence: float = 0.0
    is_pinned: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 2.5 TaskExperience（任务经验）

```python
@dataclass(slots=True)
class TaskExperience:
    lesson_digest: list[MemoryEntry]                    # 经验摘要
    domain_tips: dict[str, list[MemoryEntry]]           # 领域技巧
    agent_habits: dict[str, list[MemoryEntry]]          # Agent 习惯
```

### 2.6 MemoryEntry（通用记忆条目）

```python
@dataclass(slots=True)
class MemoryEntry:
    content: Any
    is_pinned: bool = False
```

---

## 3. Core Memory 存储

### 3.1 PostgreSQL Schema

```sql
CREATE TABLE core_memory_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    snapshot_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, version)
);

CREATE INDEX idx_core_memory_snapshots_user_created_at
    ON core_memory_snapshots (user_id, created_at DESC);
```

### 3.2 CoreMemoryStore 接口

```python
class CoreMemoryStore:
    async def load_latest(self, user_id: str) -> CoreMemory:
        """加载用户最新的 Core Memory 快照"""

    async def save_snapshot(self, user_id: str, core_memory: CoreMemory, version: int) -> None:
        """保存 Core Memory 快照（使用 UPSERT）"""

    async def list_snapshots(self, user_id: str) -> list[dict[str, Any]]:
        """列出用户所有快照版本"""
```

### 3.3 实现要点

- **懒加载连接池**：`asyncpg.create_pool` 在首次使用时创建
- **JSONB 存储**：整个 Core Memory 结构序列化为 JSONB 存储
- **UPSERT 语义**：`(user_id, version)` 唯一约束，支持版本更新

---

## 4. Core Memory 缓存

### 4.1 CoreMemoryCache 架构

```python
class CoreMemoryCache:
    """Per-user in-process core memory cache with optional Redis invalidation."""

    def __init__(self, store: CoreMemoryStore, redis_client: Any | None = None) -> None:
        self.store = store                    # CoreMemoryStore
        self.redis_client = redis_client     # 可选 Redis 客户端
        self._cache: dict[str, CoreMemory] = {}           # 进程内缓存
        self._versions: dict[str, int | None] = {}        # 版本追踪
        self._active_sessions: dict[str, set[str]] = defaultdict(set)
```

### 4.2 核心方法

```python
async def get(self, user_id: str) -> CoreMemory:
    """懒加载：从 store 加载到进程缓存"""

async def set(self, user_id: str, core_memory: CoreMemory, version: int | None = None) -> None:
    """更新缓存并发布失效广播"""

async def invalidate(self, user_id: str) -> CoreMemory:
    """重新从 store 加载，刷新缓存"""

def mark_session_active(self, user_id: str, session_id: str) -> None:
    """记录活跃 Session（用于失效广播 fan-out）"""

def mark_session_inactive(self, user_id: str, session_id: str) -> None:
    """移除 Session 记录"""
```

### 4.3 失效广播

```python
async def _publish_invalidation(self, user_id: str) -> None:
    if self.redis_client is None:
        return
    await self.redis_client.publish(
        CORE_MEMORY_INVALIDATION_CHANNEL,  # "core_memory:invalidate"
        user_id
    )
```

---

## 5. Session 上下文缓存

### 5.1 SessionContextStore 架构

```python
class SessionContextStore:
    """Store short-lived session messages and adaptations in Redis."""

    MAX_MESSAGES = 5      # 只保留最近 5 条消息
    MAX_ADAPTATIONS = 5   # 只保留最近 5 条适应
```

### 5.2 Redis Key 设计

```
session_ctx:{user_id}:{session_id}:messages     # 消息列表
session_ctx:{user_id}:{session_id}:adaptations  # 适应状态
```

### 5.3 核心方法

```python
async def append_message(self, user_id: str, session_id: str, message: dict[str, Any]) -> None:
    """追加消息，自动裁剪到 MAX_MESSAGES"""

async def get_recent_messages(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
    """获取最近消息"""

async def set_adaptations(self, user_id: str, session_id: str, adaptations: list[str]) -> None:
    """设置适应状态（Pipeline 保证原子性）"""

async def get_adaptations(self, user_id: str, session_id: str) -> list[str]:
    """获取适应状态"""

async def clear_session(self, user_id: str, session_id: str) -> None:
    """清理 Session（会话结束时调用）"""
```

### 5.4 设计原则

- **不持久化**：Session 上下文不写入 PostgreSQL，会话结束即清理
- **自动裁剪**：使用 `ltrim` 和 `rpush` 保证只保留最近 N 条
- **Pipeline 事务**：`set_adaptations` 使用 Redis Pipeline 保证原子性

---

## 6. Vector 检索

### 6.1 VectorRetriever 架构

```python
class VectorRetriever:
    """Two-level retriever backed by Qdrant and model-based reranking."""

    VECTOR_COLLECTION = "mirror_memory"
    VECTOR_NAMESPACES = frozenset({
        "experience", "self_cognition", "world_model", "dialogue_fragment"
    })
```

### 6.2 两级检索流水线

```
用户查询
    ↓
Level 0: Core Memory 缓存（直接返回）
    ↓
Level 2: Qdrant ANN 检索（召回 Top 20）
    ↓
分数方差 > 阈值？
    ↓ 是
Level 2.5: Reranker 重排序
    ↓
截取 Top 8
```

### 6.3 核心方法

```python
async def upsert(
    self,
    user_id: str,
    namespace: str,           # "experience" | "self_cognition" | "world_model" | "dialogue_fragment"
    content: str,
    metadata: dict[str, Any] | None = None,
    is_pinned: bool = False,
) -> str:
    """写入向量（自动计算 embedding）"""

async def retrieve(
    self,
    user_id: str,
    query: str,
    namespaces: list[str] | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """检索向量（返回 core_memory + matches）"""
```

### 6.4 Namespace 隔离

| Namespace | 用途 |
|-----------|------|
| `experience` | 任务执行经验 |
| `self_cognition` | 自我认知片段 |
| `world_model` | 世界模型片段 |
| `dialogue_fragment` | 对话片段 |

### 6.5 数据隔离

```python
# Qdrant payload filter 隔离
query_filter = models.Filter(must=[
    models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id)),
    models.FieldCondition(key="namespace", match=models.MatchAny(any=namespaces)),
])
```

---

## 7. Graph 存储

### 7.1 GraphStore 架构

```python
ALLOWED_RELATIONS = frozenset({
    "PREFERS",      # 用户偏好
    "DISLIKES",     # 用户厌恶
    "USES",         # 使用某工具
    "KNOWS",        # 知道某知识
    "HAS_CONSTRAINT", # 有环境约束
    "IS_GOOD_AT",   # 擅长某事
    "IS_WEAK_AT",   # 不擅长某事
})
```

### 7.2 核心方法

```python
async def upsert_relation(
    self,
    user_id: str,
    subject: str,           # 主体
    relation: str,          # 关系类型
    object: str,            # 客体
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    """写入关系（MERCGE 保证幂等）"""

async def get_relation(
    self,
    user_id: str,
    subject: str,
    relation: str,
    object: str,
) -> dict[str, Any] | None:
    """查询单个关系"""

async def query_relations_by_user(
    self,
    user_id: str,
    relation_types: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """查询用户所有关系"""

async def build_world_model_summary(self, user_id: str) -> str:
    """生成世界模型自然语言摘要"""
```

### 7.3 Neo4j 数据模型

```cypher
// 节点
(:MemoryEntity {user_id, name})

// 关系（有向边）
(s)-[r:PREFERS|DISLIKES|USES|KNOWS|HAS_CONSTRAINT|IS_GOOD_AT|IS_WEAK_AT {user_id, confidence, metadata_json, updated_at}]->(o)
```

### 7.4 关系类型词表

| 关系 | 用途 | 示例 |
|------|------|------|
| `PREFERS` | 用户偏好 | `User PREFERS 简洁回答` |
| `DISLIKES` | 用户厌恶 | `User DISLIKES 冗长解释` |
| `USES` | 使用工具 | `User USES Python` |
| `KNOWS` | 掌握知识 | `User KNOWS FastAPI` |
| `HAS_CONSTRAINT` | 环境约束 | `User HAS_CONSTRAINT 只用本地模型` |
| `IS_GOOD_AT` | 擅长领域 | `Agent IS_GOOD_AT 代码生成` |
| `IS_WEAK_AT` | 薄弱领域 | `Agent IS_WEAK_AT 数学推理` |

---

## 8. 验收标准

### 8.1 验收命令

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
```

### 8.2 验收检查项

- [ ] PostgreSQL 快照保存/加载/列表
- [ ] Redis Session 上下文追加/读取/清理
- [ ] Qdrant 向量 upsert/retrieve（含 payload 隔离）
- [ ] Neo4j 关系 upsert/query/摘要生成

### 8.3 进一步验证

```python
# Vector upsert 后检索
retriever = VectorRetriever(...)
point_id = await retriever.upsert("user1", "experience", "完成了一个 Python 项目")
results = await retriever.retrieve("user1", "项目")
assert len(results["matches"]) >= 1

# Neo4j upsert 后查询
graph = GraphStore(...)
await graph.upsert_relation("user1", "User", "PREFERS", "简洁回答", 0.9)
relations = await graph.query_relations_by_user("user1")
assert any(r["relation"] == "PREFERS" for r in relations)
```

---

## 9. 与 Phase 1 接口的对应

### 9.1 Phase 1 定义的数据结构

Phase 1 在 `app/memory/core_memory.py` 中定义了：
- `CoreMemory` + 四个区块数据类
- `BehavioralRule`

Phase 1 在 `app/evolution/event_bus.py` 中定义了：
- `InteractionSignal`、`EvolutionEntry`

### 9.2 Phase 3 的实现

| Phase 1 定义 | Phase 3 实现 |
|--------------|-------------|
| `CoreMemory` 数据类 | `app/memory/core_memory.py` 中的 dataclass 实现 |
| `CoreMemoryStore` 接口 | `app/memory/core_memory_store.py` PostgreSQL 实现 |
| `CoreMemoryCache` | `app/memory/core_memory.py` 进程内缓存 + Redis 失效 |
| `SessionContextStore` | `app/memory/session_context.py` Redis 实现 |
| `VectorRetriever` | `app/memory/vector_retriever.py` Qdrant 实现 |
| `GraphStore` | `app/memory/graph_store.py` Neo4j 实现 |

---

## 附：Explicitly Not Done Yet

以下功能在 Phase 3 中未实现：

- [ ] world-model snapshot rebuild scheduler
- [ ] automatic graph-to-core-memory snapshot synthesis
- [ ] Redis pub/sub invalidation subscriber loop
- [ ] LRU retrieval cache mentioned in architecture `Level 1`
- [ ] long-term eviction and compression policies for vector memory

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-0-学习笔记]] — Phase 0 学习笔记
- [[Phase-1-学习笔记]] — Phase 1 学习笔记
- [[Phase-2-学习笔记]] — Phase 2 学习笔记
- [[Phase-4-学习笔记|Phase 4]] — 前台推理链路（待完成）
