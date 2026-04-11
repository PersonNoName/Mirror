# Mirror

Mirror 是一个本地优先的长期陪伴型 AI Agent 运行时。它把同步对话、异步任务、长期记忆、关系演化和受控治理放在同一套系统里，目标不是只回答一次，而是在多轮互动中保持上下文、积累记忆，并让行为逐步稳定下来。

当前实现基于 `FastAPI + asyncio`，并使用：

- PostgreSQL：结构化状态与任务主存储
- Redis：事件流、热路径缓存、会话上下文
- Neo4j：关系图谱
- Qdrant：语义检索
- OpenAI-compatible providers：主推理、抽取、embedding、reranker

## 系统目标

- 提供可直接接入的对话 API 与流式输出能力
- 支持任务分发、异步执行和 HITL（human-in-the-loop）反馈
- 支持用户长期记忆、关系状态、记忆治理与纠错
- 支持对话结束后的观察、反思、认知更新与温和主动性
- 保持单机优先、可降级运行，方便后续扩展 Skill / Tool / MCP / Agent

## 技术栈

- Python 3.11+
- FastAPI / Uvicorn
- PostgreSQL
- Redis
- Neo4j
- Qdrant
- Pydantic Settings
- Structlog
- Pytest / pytest-asyncio

## 仓库结构

```text
app/
  api/          HTTP API
  agents/       内建 agent 定义
  evolution/    观察、反思、记忆更新、关系演化、主动性
  hooks/        Hook 注册与扩展点
  infra/        基础设施适配
  memory/       Core memory、图谱、向量检索、治理
  platform/     平台适配层
  providers/    模型 provider 与路由
  runtime/      启动装配与生命周期管理
  skills/       Skill loader
  soul/         核心推理与动作决策
  stability/    幂等、熔断、快照等稳定性组件
  tasks/        Task system、blackboard、worker、relay
  tools/        工具注册、builtin tool、MCP adapter
docker/         本地服务镜像与辅助服务
migrations/     PostgreSQL 初始化脚本
docs/           设计文档与运行说明
tests/          单元测试与集成测试
start.ps1       Windows 启动脚本
start.sh        Unix 启动脚本
docker-compose.yml
```

## 核心模块

### API 层

入口在 [app/main.py](C:/Users/IVES/Documents/Code/Projects/Mirror/app/main.py)。

主要接口：

- `POST /chat`
- `GET /chat/stream`
- `POST /hitl/respond`
- `GET /memory`
- `GET /memory/governance`
- `POST /memory/governance/block`
- `POST /memory/correct`
- `POST /memory/delete`
- `GET /evolution/journal`

### Runtime 装配层

入口在 [app/runtime/bootstrap.py](C:/Users/IVES/Documents/Code/Projects/Mirror/app/runtime/bootstrap.py)。

这里负责：

- 初始化 PostgreSQL / Redis / Neo4j / Qdrant
- 装配 provider registry、memory、event bus、task system
- 注册内建 agent、tool、hook、skill、MCP
- 启动 `OutboxRelay`、`TaskMonitor`、`TaskWorkerManager`、`EvolutionScheduler`
- 暴露统一健康状态

### Soul 层

位于 `app/soul/`。

- `SoulEngine`：读取输入、结合记忆和上下文做动作决策
- `ActionRouter`：把动作转成回复、任务、HITL 等实际执行结果

### Memory 层

位于 `app/memory/`。

- `CoreMemoryStore` / `CoreMemoryCache`
- `SessionContextStore`
- `GraphStore`
- `VectorRetriever`
- `MemoryGovernanceService`

职责划分：

- PostgreSQL：主状态与持久化任务
- Redis：会话上下文、事件流、热缓存
- Neo4j：长期关系图谱
- Qdrant：语义召回

### Evolution 层

位于 `app/evolution/`。

主要组件：

- `ObserverEngine`
- `MetaCognitionReflector`
- `CognitionUpdater`
- `PersonalityEvolver`
- `RelationshipStateMachine`
- `CoreMemoryScheduler`
- `EvolutionJournal`
- `GentleProactivityService`
- `SignalExtractor`

这一层负责把“对话后的变化”放进异步链路，而不是在主回复链路里直接写死。

## 本地依赖服务

项目默认使用以下本地服务：

- PostgreSQL
- Redis
- Neo4j
- Qdrant
- OpenCode stub
- Reranker service

这些服务由 [docker-compose.yml](C:/Users/IVES/Documents/Code/Projects/Mirror/docker-compose.yml) 提供。

## 快速开始

### 方式一：使用启动脚本

Windows:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
./start.ps1
```

Linux / macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start.sh
```

### 方式二：手动启动

1. 安装依赖

```powershell
pip install -r requirements.txt
```

2. 准备环境变量

```powershell
Copy-Item .env.example .env
```

3. 启动基础设施

```powershell
docker compose up -d
```

4. 启动应用

```powershell
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

5. 健康检查

- 应用：`http://127.0.0.1:8000/health`
- reranker：`http://127.0.0.1:8081/health`

## 配置说明

统一配置在 [app/config.py](C:/Users/IVES/Documents/Code/Projects/Mirror/app/config.py)，由 `.env` 注入。

常用配置分组：

- 应用：`APP_*`
- PostgreSQL：`POSTGRES_*`
- Redis：`REDIS_*`
- Neo4j：`NEO4J_*`
- Qdrant：`QDRANT_*`
- OpenCode：`OPENCODE_*`
- 主推理模型：`MODEL_REASONING_MAIN_*`
- 轻量抽取模型：`MODEL_LITE_EXTRACTION_*`
- 检索 embedding：`MODEL_RETRIEVAL_EMBEDDING_*`
- 检索 reranker：`MODEL_RETRIEVAL_RERANKER_*`
- reranker 服务自身：`RERANKER_*`
- 扩展加载：`SKILLS_DIR`、`MCP_SERVERS_FILE`、`MCP_SERVERS_JSON`

## Retrieval Models

项目里检索侧有两种模型角色：

- `MODEL_RETRIEVAL_EMBEDDING_*`
  - 供应用把文本转成向量，用于 Qdrant 召回
- `MODEL_RETRIEVAL_RERANKER_*`
  - 供应用在召回后调用 reranker 服务做重排

这两类都不是主对话模型。

### `MODEL_RETRIEVAL_RERANKER_*` 的作用

这组变量告诉应用如何访问 reranker 服务：

```env
MODEL_RETRIEVAL_RERANKER_PROVIDER_TYPE=openai_compatible
MODEL_RETRIEVAL_RERANKER_VENDOR=local
MODEL_RETRIEVAL_RERANKER_MODEL=reranker-v1
MODEL_RETRIEVAL_RERANKER_BASE_URL=http://127.0.0.1:8081
MODEL_RETRIEVAL_RERANKER_API_KEY=
```

含义：

- `PROVIDER_TYPE=openai_compatible`
  - 应用通过 OpenAI-compatible reranker 适配器发请求
- `VENDOR=local`
  - 逻辑标签，用来表示本地服务
- `MODEL=reranker-v1`
  - 业务侧模型别名
- `BASE_URL=http://127.0.0.1:8081`
  - 本地 reranker HTTP 服务地址

### `RERANKER_*` 的作用

这组变量是 reranker 容器自己的运行参数，不是应用侧路由：

```env
RERANKER_PORT=8081
RERANKER_MODEL_ID=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=cpu
RERANKER_BATCH_SIZE=16
RERANKER_LOCAL_MODEL_ROOT=/models/local-reranker
```

含义：

- `RERANKER_PORT`
  - 容器服务端口
- `RERANKER_MODEL_ID`
  - 容器内部真正加载的 Hugging Face 模型
- `RERANKER_DEVICE`
  - `cpu`、`cuda` 或 `auto`
- `RERANKER_BATCH_SIZE`
  - 本地推理批大小
- `RERANKER_LOCAL_MODEL_ROOT`
  - 容器内部的本地模型挂载目录

## 本地 Reranker 服务

项目现在包含一个本地 Docker reranker 服务：

- 定义：[docker-compose.yml](C:/Users/IVES/Documents/Code/Projects/Mirror/docker-compose.yml)
- 服务实现：[docker/reranker/server.py](C:/Users/IVES/Documents/Code/Projects/Mirror/docker/reranker/server.py)
- 说明文档：[docs/reranker-service.md](C:/Users/IVES/Documents/Code/Projects/Mirror/docs/reranker-service.md)

支持的接口：

- `GET /health`
  - 轻量 liveness 检查，不触发模型加载
- `GET /ready`
  - 返回默认模型是否已经加载完成
- `POST /rerank`
  - 真正执行重排，第一次调用时会懒加载模型

推荐检查方式：

```powershell
docker compose up -d --build reranker
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8081/health | Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8081/ready | Select-Object -ExpandProperty Content
```

预期：

- `/health` 应该快速返回
- `/ready` 初始可能是 `starting`
- 第一次成功 `POST /rerank` 后，`/ready` 会变成 `ok`

当前 compose 已支持把主机 Hugging Face 缓存目录挂载到容器里，优先从本地快照加载 `BAAI/bge-reranker-v2-m3`，避免首次联网下载。

## 典型请求示例

### 对话

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "text": "帮我规划一下今天的学习安排",
    "session_id": "session-1",
    "user_id": "user-1"
  }'
```

### 流式输出

```bash
curl -N "http://127.0.0.1:8000/chat/stream?session_id=session-1"
```

### HITL 反馈

```bash
curl -X POST http://127.0.0.1:8000/hitl/respond \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task-1",
    "decision": "approve",
    "payload": {
      "safe": true
    }
  }'
```

### 查看记忆

```bash
curl "http://127.0.0.1:8000/memory?user_id=user-1"
```

### 查看进化日志

```bash
curl "http://127.0.0.1:8000/evolution/journal?limit=10&user_id=user-1"
```

## 测试

运行全部测试：

```powershell
pytest
```

运行部分测试：

```powershell
pytest tests/test_runtime_bootstrap.py
pytest tests/test_soul_engine.py
pytest tests/test_observer_preferences.py
pytest tests/test_relationship_memory.py
```

## 开发建议

- 新能力优先接到 `app/runtime/bootstrap.py` 统一装配
- 不要在业务代码里直接硬编码模型 SDK，通过 provider registry 注入
- 平台相关能力通过 platform adapter 接入
- 用户可控、可纠错、可回滚的行为优先接入 memory governance / evolution pipeline
- 对于偏好记忆，优先区分显式 fact、隐式 inference、短期 session hint、待确认 candidate

## 相关文档

- [main_agent_architecture_v3.4.md](C:/Users/IVES/Documents/Code/Projects/Mirror/main_agent_architecture_v3.4.md)
- [PLAN.md](C:/Users/IVES/Documents/Code/Projects/Mirror/PLAN.md)
- [LONG_TERM_COMPANION_PLAN.md](C:/Users/IVES/Documents/Code/Projects/Mirror/LONG_TERM_COMPANION_PLAN.md)
- [OPTIMIZATION_PLAN.md](C:/Users/IVES/Documents/Code/Projects/Mirror/OPTIMIZATION_PLAN.md)
- [docs/preference-memory-pipeline.md](C:/Users/IVES/Documents/Code/Projects/Mirror/docs/preference-memory-pipeline.md)
- [docs/reranker-service.md](C:/Users/IVES/Documents/Code/Projects/Mirror/docs/reranker-service.md)
