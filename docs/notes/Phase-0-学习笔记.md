# Phase 0 学习笔记：项目脚手架

## 目录

- [概述](#概述)
- [1. Docker Compose 服务编排](#1-docker-compose-服务编排)
- [2. 项目结构](#2-项目结构)
- [3. 依赖管理](#3-依赖管理)
- [4. 配置体系](#4-配置体系)
- [5. 应用入口](#5-应用入口)
- [6. 数据库迁移](#6-数据库迁移)
- [7. 验收标准](#7-验收标准)
- [8. 关键设计原则](#8-关键设计原则)

---

## 概述

Phase 0 是整个项目的起点，目标是建立**可运行的项目骨架**，所有基础服务就绪。本阶段**不写任何业务逻辑**。

### 核心交付物

| 组件 | 说明 |
|------|------|
| Docker Compose | 5 个本地服务（PostgreSQL、Redis、Neo4j、Qdrant、OpenCode） |
| 项目结构 | 完整的目录骨架和空模块文件（`__init__.py`） |
| 依赖声明 | `requirements.txt` |
| 配置入口 | `app/config.py` + `.env.example` |
| 应用入口 | `app/main.py` + `/health` 端点 |
| 数据库表 | `outbox_events`、`stream_consumers`、`idempotency_keys` |

---

## 1. Docker Compose 服务编排

### 1.1 服务列表

```yaml
services:
  postgres:   # PostgreSQL 16 - 系统主事实库
  redis:      # Redis 7 - Streams + KV + Pub/Sub
  neo4j:      # Neo4j 5.22 - 图数据库
  qdrant:     # 向量检索引擎
  opencode:   # OpenCode 代码执行服务
```

### 1.2 服务配置要点

#### PostgreSQL
```yaml
postgres:
  image: postgres:16-alpine
  ports:
    - "${POSTGRES_PORT:-5432}:5432"
  volumes:
    - postgres_data:/var/lib/postgresql/data
    - ./migrations:/docker-entrypoint-initdb.d:ro  # 自动执行迁移脚本
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
```

#### Redis
```yaml
redis:
  image: redis:7-alpine
  command: ["redis-server", "--appendonly", "yes", "--save", "60", "1"]
  # AOF 持久化：每 60 秒有 1 次修改则触发持久化
```

#### Neo4j
```yaml
neo4j:
  image: neo4j:5.22-community
  environment:
    NEO4J_AUTH: "${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:-mirrorneo4j}"
  ports:
    - "7474:7474"  # HTTP
    - "7687:7687"  # Bolt 协议
```

#### Qdrant
```yaml
qdrant:
  build:
    context: .
    dockerfile: docker/qdrant-tools/Dockerfile
  # 自定义 Dockerfile 构建
```

#### OpenCode
```yaml
opencode:
  build:
    context: .
    dockerfile: docker/opencode-stub/Dockerfile
  volumes:
    - opencode_data:/var/lib/opencode
```

### 1.3 持久化卷

```yaml
volumes:
  postgres_data:      # PostgreSQL 数据
  redis_data:        # Redis 数据
  neo4j_data_phase0: # Neo4j 数据
  neo4j_logs_phase0: # Neo4j 日志
  qdrant_data_phase0: # Qdrant 存储
  opencode_data:     # OpenCode 数据
```

---

## 2. 项目结构

### 2.1 目录树

```
app/
├── __init__.py
├── main.py              # FastAPI 应用入口
├── config.py            # 配置管理
├── logging.py           # 日志配置
├── agents/              # SubAgent 模块
│   └── __init__.py
├── api/                 # API 路由
│   └── __init__.py
├── evolution/           # 后台进化层
│   └── __init__.py
├── hooks/               # Hook 机制
│   └── __init__.py
├── infra/               # 基础设施
│   └── __init__.py
├── memory/              # 记忆系统
│   └── __init__.py
├── platform/            # 平台适配层
│   └── __init__.py
├── providers/          # 模型提供者
│   └── __init__.py
├── stability/          # 稳定性保障
│   └── __init__.py
├── tasks/              # 任务系统
│   └── __init__.py
└── tools/              # 工具注册
    └── __init__.py
```

### 2.2 模块职责（后续 Phase 填充）

| 模块 | 职责 |
|------|------|
| `agents/` | SubAgent 抽象接口、CodeAgent、WebAgent 实现 |
| `api/` | REST API 路由（chat、hitl、journal） |
| `evolution/` | EventBus、Observer、Reflector、CognitionUpdater 等 |
| `hooks/` | 钩子机制（PRE_REASON、POST_REASON、PRE_TASK、POST_REPLY） |
| `infra/` | 基础设施（OutboxRelay 等） |
| `memory/` | VectorRetriever、GraphStore、CoreMemoryStore、CoreMemoryCache |
| `platform/` | PlatformAdapter、WebPlatformAdapter |
| `providers/` | ModelProviderRegistry、OpenAI兼容客户端 |
| `stability/` | CircuitBreaker、Snapshot、Idempotency |
| `tasks/` | TaskSystem、Blackboard、Outbox |
| `tools/` | ToolRegistry、MCPAdapter |

---

## 3. 依赖管理

### 3.1 requirements.txt

```
fastapi>=0.115,<1.0          # Web 框架
uvicorn[standard]>=0.30,<1.0  # ASGI 服务器
httpx>=0.27,<1.0            # HTTP 客户端
httpx-sse>=0.4,<1.0         # SSE 支持
qdrant-client>=1.9,<2.0    # Qdrant Python SDK
redis>=5.0,<6.0             # Redis Python 客户端
asyncpg>=0.29,<1.0          # async PostgreSQL 驱动
neo4j>=5.20,<6.0            # Neo4j Python 驱动
pydantic-settings>=2.3,<3.0 # 环境变量配置
structlog>=24.1,<25.0       # 结构化日志
```

### 3.2 依赖设计原则

- **异步优先**：选择 `asyncpg` 而非 `psycopg2`，选择 `httpx` 而非 `requests`
- **版本约束**：使用 `>=x,<y` 范围约束，避免 Breaking Change
- **最小依赖**：不引入不必要的库

---

## 4. 配置体系

### 4.1 配置架构

```
环境变量 (.env)
    ↓
pydantic-settings (BaseSettings)
    ↓
Settings 类 (app/config.py)
    ↓
各子配置类 (AppConfig, PostgresConfig, ...)
```

### 4.2 pydantic-settings 工作原理

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",           # 读取 .env 文件
        env_file_encoding="utf-8",
        case_sensitive=False,      # 环境变量名不区分大小写
        extra="ignore",            # 忽略额外环境变量
    )
    
    # 环境变量自动映射
    POSTGRES_HOST: str = "127.0.0.1"
    POSTGRES_PORT: int = 5432
```

### 4.3 配置分层

```python
class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str
    APP_ENV: str
    
    # PostgreSQL 配置
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str
    ...
    
    # 衍生配置类（通过 @property）
    @property
    def postgres(self) -> PostgresConfig:
        return PostgresConfig(...)
```

### 4.4 .env vs .env.example

| 文件 | 用途 | Git |
|------|------|-----|
| `.env` | 运行时实际配置，**包含敏感信息** | ❌ 不提交 |
| `.env.example` | 配置模板，供开发者参考 | ✅ 提交 |

### 4.5 配置读取优先级

1. 环境变量（最高优先）
2. `.env` 文件
3. `Settings` 类默认值（最低优先）

---

## 5. 应用入口

### 5.1 FastAPI 应用结构

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

# 1. 日志配置
configure_logging(settings.app.log_level)
logger = structlog.get_logger(__name__)

# 2. 生命周期管理
@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("app_startup", ...)
    yield
    logger.info("app_shutdown", ...)

# 3. 创建应用
app = FastAPI(title=settings.app.name, lifespan=lifespan)

# 4. 健康检查端点
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

### 5.2 生命周期钩子

- **startup**：初始化连接、资源预加载
- **shutdown**：优雅关闭、连接清理
- `asynccontextmanager` 确保 startup 和 shutdown 配对执行

---

## 6. 数据库迁移

### 6.1 自动执行机制

```yaml
volumes:
  - ./migrations:/docker-entrypoint-initdb.d:ro
```

PostgreSQL 镜像的 `docker-entrypoint-initdb.d` 目录中的 `.sql` 文件会在数据库**首次初始化**时自动执行。

### 6.2 Phase 0 基础表

#### outbox_events（消息发件箱）

```sql
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    topic TEXT NOT NULL,              -- 消息主题/队列名
    payload JSONB NOT NULL,            -- 消息内容
    status TEXT NOT NULL DEFAULT 'pending',  -- 状态：pending/published/failed
    retry_count INTEGER DEFAULT 0,     -- 重试次数
    next_retry_at TIMESTAMPTZ,         -- 下次重试时间
    created_at TIMESTAMPTZ DEFAULT NOW(),
    published_at TIMESTAMPTZ           -- 发布时间
);

CREATE INDEX idx_outbox_events_status_created_at 
    ON outbox_events (status, created_at);
```

**用途**：实现 Outbox Pattern，保证业务状态变更和事件投递的原子性。

#### stream_consumers（流消费者状态）

```sql
CREATE TABLE stream_consumers (
    id UUID PRIMARY KEY,
    consumer_name TEXT NOT NULL,      -- 消费者名称
    stream_name TEXT NOT NULL,         -- 流名称
    group_name TEXT NOT NULL,          -- 消费者组
    last_heartbeat_at TIMESTAMPTZ,     -- 最后心跳时间
    last_delivered_id TEXT,            -- 最后投递的消息 ID
    pending_count INTEGER DEFAULT 0,    -- 待处理消息数
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (consumer_name, stream_name, group_name)
);
```

**用途**：追踪 Redis Streams 消费者状态，用于故障恢复。

#### idempotency_keys（幂等键）

```sql
CREATE TABLE idempotency_keys (
    id UUID PRIMARY KEY,
    scope TEXT NOT NULL,               -- 作用域（如 "chat", "task"）
    key TEXT NOT NULL,                  -- 幂等键值
    status TEXT DEFAULT 'pending',      -- 状态
    response_payload JSONB,             -- 响应缓存
    expires_at TIMESTAMPTZ,             -- 过期时间
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (scope, key)
);
```

**用途**：防止重复操作（如重复发送消息、重复执行任务）。

---

## 7. 验收标准

### 7.1 验收命令

```bash
# 1. 启动所有服务
docker compose up -d && docker compose ps

# 2. 启动 FastAPI 应用
uvicorn app.main:app --port 8000

# 3. 验证健康检查
curl http://localhost:8000/health
# 期望返回：{"status": "ok"}
```

### 7.2 验收检查项

- [ ] `docker compose ps` 显示所有 5 个服务状态为 `running`
- [ ] `uvicorn` 启动无 ImportError 或配置错误
- [ ] `/health` 端点返回 200 状态码
- [ ] PostgreSQL 中存在 3 张基础表

---

## 8. 关键设计原则

### 8.1 Outbox Pattern

**问题**：先写数据库、再写消息队列的非原子操作可能导致数据不一致。

**解决方案**：

```
业务事务
    ↓
同时写入：业务表 + outbox_events 表
    ↓
独立 OutboxRelay 进程
    ↓
轮询 outbox_events → 投递到 Redis Streams
    ↓
标记 published_at
```

### 8.2 配置即代码

- 所有配置通过环境变量注入
- 不在代码中硬编码连接字符串、密码等
- `.env.example` 提供完整配置清单

### 8.3 异步优先

- 全链路 asyncio
- 使用 `asyncpg`、`redis.asyncio` 等异步驱动
- 非阻塞 I/O 确保高并发

### 8.4 服务职责分层

| 存储 | 职责 |
|------|------|
| PostgreSQL | 状态真相源（任务、会话、Core Memory 快照、Journal） |
| Redis | 搬运层（Streams 队列、热缓存、Pub/Sub 通知） |
| Neo4j | 长期关系图谱（偏好、能力判断、环境约束） |
| Qdrant | 语义检索（情境经验、对话片段、反思结果） |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[../main_agent_architecture_v3.4.md|架构文档]] — 详细架构参考
- [[../.env.example|.env.example]] — 环境变量模板
