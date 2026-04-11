# Phase 7 学习笔记：扩展注册表与集成层

> **前置阶段**：[[Phase-6-学习笔记]]  
> **目标**：把工具、Hook、Sub-Agent、Skill、MCP 这些扩展点从核心链路中抽离出来，形成统一的注册与启动机制  
> **里程碑**：本阶段完成后系统首次具备“通过注册表和加载器扩展运行时能力”的基础框架

---

## 目录

- [概述](#概述)
- [1. Phase 7 文件清单](#1-phase-7-文件清单)
- [2. 为什么需要扩展层](#2-为什么需要扩展层)
- [3. Runtime Bootstrap](#3-runtime-bootstrap)
- [4. ToolRegistry](#4-toolregistry)
- [5. HookRegistry](#5-hookregistry)
- [6. AgentRegistry 升级](#6-agentregistry-升级)
- [7. SkillLoader](#7-skillloader)
- [8. MCPToolAdapter](#8-mcptooladapter)
- [9. `tool_call` 前台执行链路](#9-tool_call-前台执行链路)
- [10. Health 与启动脚本](#10-health-与启动脚本)
- [11. 启动流程](#11-启动流程)
- [12. 优雅降级策略](#12-优雅降级策略)
- [13. 验收标准](#13-验收标准)

---

## 概述

### 目标

Phase 7 的目标不是新增一个业务能力，而是**把系统变得更可扩展**。

Phase 6 之前，Mirror 已经具备：

- 前台同步推理链路
- 后台任务执行链路
- 后台进化学习链路

但这些能力的扩展方式还比较硬编码：

- 新工具往往要直接改核心文件
- 新 hook 没有统一注册协议
- 新 agent 也主要靠手工 wiring
- 启动装配集中在 `app/main.py`，越来越臃肿

Phase 7 的工作就是把这些“扩展入口”抽象出来。

### Phase 7 解决的核心问题

- 把启动 wiring 从 `app/main.py` 抽到统一 bootstrap
- 给 tool / hook / agent 建立结构化注册表
- 允许本地 skill manifest 自动注册扩展
- 支持最小可用的 MCP 工具接入
- 让前台 `tool_call` 真正走统一工具执行路径

### 新的系统形态

```text
Bootstrap
    ↓
Built-in Registry Registration
    ↓
Skill Loader
    ↓
MCP Loader
    ↓
Foreground / Background Runtime
    ↓
统一通过 Registry / Loader 扩展
```

这意味着后续新增能力时，优先考虑：

- 注册
- 加载
- 描述

而不是直接修改核心链路代码。

---

## 1. Phase 7 文件清单

| 文件 | 内容 |
|------|------|
| `app/runtime/bootstrap.py` | 统一运行时装配、启动、停止、健康快照 |
| `app/main.py` | 精简后的 FastAPI 入口 |
| `app/tools/registry.py` | ToolRegistry 结构化注册与调用协议 |
| `app/hooks/registry.py` | HookRegistry 与 HookPoint |
| `app/agents/registry.py` | 带 source / overwrite 的 AgentRegistry |
| `app/tools/builtin_tools.py` | 内建示例工具注册 |
| `app/skills/loader.py` | 基于 manifest 的本地 skill 加载器 |
| `app/tools/mcp_adapter.py` | 最小可用 MCP 工具加载与转发 |
| `app/soul/engine.py` | 接入 hook 触发点 |
| `app/soul/router.py` | `tool_call` 执行路径与 hook 触发点 |
| `start.ps1` | Windows 启动脚本 |
| `start.sh` | Unix 启动脚本 |
| `skills/` | 本地示例 skill |

---

## 2. 为什么需要扩展层

### 2.1 Phase 6 之前的问题

随着系统组件变多，原来的直接 wiring 方式开始暴露问题：

- `main.py` 越来越像总装脚本
- 新工具没有统一元数据描述
- Prompt 里虽然能提“工具”，但工具本身不一定可枚举、可调用
- 本地扩展和远端工具接入缺少统一模型

### 2.2 Phase 7 的思路

Phase 7 引入的不是“插件市场”，而是一套基础设施：

- registry：负责保存能力
- loader：负责把外部定义装进 registry
- bootstrap：负责统一组装 runtime

这三者组合之后，系统扩展的基本模式就稳定了：

```text
定义能力
    ↓
注册到 registry
    ↓
通过 bootstrap 装配到 runtime
    ↓
在前台或后台链路中被统一消费
```

### 2.3 核心原则

- 前台工具执行只能走 `ToolRegistry.invoke()`
- 新扩展优先通过 loader 和 manifest 注入
- 注册表要保留来源信息 `source`
- 单个扩展失败不能拖死整个 app 启动

---

## 3. Runtime Bootstrap

### 3.1 从 `main.py` 中抽离

Phase 7 最明显的重构是：

- 复杂 wiring 从 `app/main.py` 抽到 `app/runtime/bootstrap.py`
- `app/main.py` 只保留 FastAPI 入口和 `/health`

现在的 `main.py` 非常薄：

```python
app = FastAPI(title=settings.app.name, lifespan=runtime_lifespan)
app.include_router(chat_router)
app.include_router(hitl_router)
app.include_router(journal_router)
```

这说明 Phase 7 已经把“应用入口”和“运行时装配”分层了。

### 3.2 RuntimeContext

`bootstrap.py` 用 `RuntimeContext` 作为总容器：

```python
@dataclass(slots=True)
class RuntimeContext:
    redis_client: Redis | None
    model_registry: ModelProviderRegistry
    outbox_store: OutboxStore
    ...
    skill_loader: SkillLoader
    mcp_adapter: MCPToolAdapter
    skill_summary: dict[str, Any]
    mcp_summary: dict[str, Any]
    builtins_summary: dict[str, Any]
```

它的价值在于：

- 所有 runtime 组件有统一归属
- 可以一键 bind 到 `app.state`
- `/health` 可以直接读取整套 runtime 快照

### 3.3 Bootstrap 生命周期

Phase 7 把运行时生命周期拆成四段：

```python
async def bootstrap_runtime() -> RuntimeContext: ...
async def start_runtime(runtime: RuntimeContext) -> None: ...
async def stop_runtime(runtime: RuntimeContext) -> None: ...
def bind_runtime_state(app: FastAPI, runtime: RuntimeContext) -> None: ...
```

这是一个很重要的工程升级：

- 创建对象
- 启动后台任务
- 关闭后台任务
- 绑定到 Web App

这几件事现在各自独立，后面更容易测试和演化。

---

## 4. ToolRegistry

### 4.1 结构化定义

Phase 7 之前工具更多是“能不能调起来”，Phase 7 开始变成“能不能被统一描述、注册、调用”。

```python
@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str = ""
    schema: dict[str, Any] = field(default_factory=dict)
    source: str = "runtime"
    callable: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

一个工具现在不仅有 callable，还有：

- `description`
- `schema`
- `source`
- `metadata`

这意味着工具已经不是“裸函数”，而是 runtime capability。

### 4.2 注册协议

`ToolRegistry.register()` 支持两种风格：

- 直接注册
- 装饰器注册

```python
@tool_registry.register(
    name="get_current_time",
    description="Return the current UTC time in ISO-8601 format.",
    schema={...},
    source="builtin",
)
async def get_current_time(...):
    ...
```

这种模式后续非常适合：

- 内建工具
- skill 工具
- MCP 代理工具

### 4.3 描述能力

```python
def describe_tools(self) -> list[dict[str, Any]]:
    return [
        {
            "name": definition.name,
            "description": definition.description,
            "schema": definition.schema,
            "source": definition.source,
            "metadata": dict(definition.metadata),
        }
        ...
    ]
```

这一步直接影响了前台 prompt 组装，因为 `SoulEngine` 现在会把结构化工具列表拼进 prompt。

### 4.4 调用协议

```python
async def invoke(self, name: str, params: dict[str, Any] | None = None, context: Any = None) -> Any:
    ...
```

`invoke()` 负责统一处理：

- 取 definition
- 调 callable
- 兼容不同函数签名
- await async result
- 统一包裹异常为 `ToolInvocationError`

这让调用方不再需要知道：

- 这个工具是 sync 还是 async
- 它是否接受 `context`
- 它来自 builtin、skill 还是 MCP

---

## 5. HookRegistry

### 5.1 HookPoint

Phase 7 给前台链路补上了结构化 hook 点：

```python
class HookPoint(StrEnum):
    PRE_REASON = "pre_reason"
    POST_REASON = "post_reason"
    PRE_TASK = "pre_task"
    POST_REPLY = "post_reply"
```

这些点位覆盖的是前台推理链路里最关键的几个阶段：

- 推理前
- 推理后
- 派任务前
- 回复发送后

### 5.2 HookDefinition

```python
@dataclass(slots=True)
class HookDefinition:
    hook_point: HookPoint
    handler: HookHandler
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)
```

和工具一样，hook 现在也保留了来源信息。

### 5.3 触发方式

`HookRegistry.trigger()` 是 best-effort：

```python
async def trigger(self, hook_point: HookPoint, **payload: Any) -> None:
    for definition in self.get_handlers(hook_point):
        try:
            await definition.handler(**payload)
        except Exception:
            logger.exception(...)
```

这里的关键策略是：

- hook 失败只记录日志
- 不打断主链路

这很重要，因为 hook 是扩展点，不应该反过来绑架主流程。

### 5.4 接入点

目前已经接入：

- `SoulEngine.run()`：
  - `PRE_REASON`
  - `POST_REASON`
- `ActionRouter.route()`：
  - `PRE_TASK`
  - `POST_REPLY`

这使得 Phase 7 的 hook 已经不仅是“注册了”，而是真的进入了核心前台链路。

---

## 6. AgentRegistry 升级

### 6.1 从单纯容器到带来源元数据的注册表

Phase 5 的 `AgentRegistry` 主要用于查找 agent。  
Phase 7 开始，它也带有结构化 registration：

```python
@dataclass(slots=True)
class AgentRegistration:
    agent: SubAgent
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)
```

### 6.2 覆盖控制

```python
def register(..., overwrite: bool = True, ...) -> SubAgent:
    existing = self._agents.get(agent.name)
    if existing is not None and not overwrite:
        ...
        return existing.agent
```

这意味着：

- 内建 agent 可以作为默认值
- skill agent 可以选择覆盖
- 也可以选择保留已有 agent

这是后面做扩展优先级控制的基础。

### 6.3 描述接口

```python
def describe(self) -> list[dict[str, Any]]:
    return [
        {
            "name": registration.agent.name,
            "domain": registration.agent.domain,
            "source": registration.source,
            "metadata": dict(registration.metadata),
        }
    ]
```

说明 agent 也开始被视作一类可枚举的 runtime extension，而不只是代码对象。

---

## 7. SkillLoader

### 7.1 本地 manifest 驱动

Phase 7 增加了本地 skill 目录加载器：

```python
class SkillLoader:
    def __init__(..., skills_dir="skills", ...):
        ...
```

它会扫描 `skills/` 下的：

- `.json`
- `.yaml`
- `.yml`

manifest，然后注册对应能力。

### 7.2 支持的 skill 类型

当前支持三类：

- `tool`
- `hook`
- `sub_agent`

```python
if manifest_type == "tool":
    self._register_tool(...)
if manifest_type == "hook":
    self._register_hook(...)
if manifest_type == "sub_agent":
    self._register_agent(...)
```

这说明 Phase 7 的本地扩展边界已经比较清晰。

### 7.3 Target 解析

skill manifest 使用：

```text
module_name:attr.path
```

例如：

```text
skills.sample_tools:get_current_time
```

加载器通过 `importlib` 动态解析目标对象，再注册到对应 registry。

### 7.4 加载总结

`load_all()` 返回：

```python
{"loaded": [], "skipped": [], "failed": []}
```

这让 bootstrap 不只是“调用加载器”，还能拿到结构化结果写进 health。

### 7.5 降级行为

skill loader 的设计明显偏实用：

- `skills/` 不存在 -> 记为 skipped，app 继续启动
- 某个 manifest 非法 -> 只失败这一项，其他继续加载

也就是说，它强调“局部失败隔离”。

---

## 8. MCPToolAdapter

### 8.1 V1 的定位

MCP 接入在 Phase 7 明确是 V1-minimal，不追求完整协议支持，只先把最小闭环打通：

- 读取配置
- 调 `tools/list`
- 注册为本地代理工具
- 调 `tools/call`

### 8.2 服务器配置来源

配置可以来自两处：

- `servers_json`
- `servers_file`

这使得 MCP 既可以走环境注入，也可以走本地 JSON 文件。

### 8.3 加载方式

```python
tools = await self._list_tools(server)
...
self.tool_registry.register(
    name=tool_name,
    tool=self._build_proxy(server, tool_name),
    description=str(tool.get("description", "")),
    schema=dict(tool.get("inputSchema", {}) or {}),
    source=f"mcp:{server.name}",
    metadata={...},
)
```

关键点在于：

- MCP 工具最终也注册进同一个 `ToolRegistry`
- 所以前台调用时不需要区分“本地工具”还是“远端 MCP 工具”

### 8.4 转发方式

```python
payload = {
    "jsonrpc": "2.0",
    "id": f"tools-call:{tool_name}",
    "method": "tools/call",
    "params": {"name": tool_name, "arguments": params or {}},
}
```

这说明当前 Phase 7 的 MCP 主要是：

- 一个轻量 RPC 转发器
- 不做复杂会话管理
- 不做高级认证协商

### 8.5 故障隔离

如果某个 MCP server 加载失败：

- 只记到 `summary["failed"]`
- 不阻塞其他 server
- 不阻塞 app 启动

这也是整个 Phase 7 扩展层最核心的风格之一。

---

## 9. `tool_call` 前台执行链路

### 9.1 之前的问题

在更早的阶段里，`tool_call` 更多像一个 Action 类型占位。  
Phase 7 之后，它第一次有了**标准执行路径**。

### 9.2 Action 内容格式

`tool_call` 要求模型输出的 `content` 是 JSON：

```json
{"name": "...", "arguments": {...}}
```

对应解析逻辑：

```python
payload = json.loads(raw)
name = str(payload.get("name", "")).strip()
arguments = payload.get("arguments", {})
```

### 9.3 真正调用路径

```python
result = await self.tool_registry.invoke(tool_name, params, context=context)
```

这是 Phase 7 最重要的 handoff 规则之一：

- 前台工具调用不再直接调某个函数
- 一律走 `ToolRegistry.invoke()`

### 9.4 结果处理

```python
if isinstance(result, str):
    return result
return json.dumps(result, ensure_ascii=False, default=str)
```

也就是说，工具结果最终还是会被转成对用户可见的文本回复。

### 9.5 降级策略

`tool_call` 的失败不会抛到前台崩掉，而是降级成说明性回复：

- payload 解析失败
- 工具没注册
- 工具调用异常

例如：

- `工具调用解析失败，已降级为直接回复`
- `工具 xxx 未注册，已降级为直接回复`
- `工具 xxx 调用失败：...`

这让工具链路在 V1 阶段更适合作为“可选增强”，而不是硬依赖。

---

## 10. Health 与启动脚本

### 10.1 聚合 Health

Phase 7 的 `/health` 不再只是简单 `{"status": "ok"}`，而是读取 runtime 快照：

```python
runtime_health = getattr(app.state, "runtime_health", None)
if callable(runtime_health):
    return runtime_health()
```

真正的数据来自：

```python
RuntimeContext.health_snapshot()
```

### 10.2 子系统快照

当前会汇总：

- `app`
- `postgres`
- `redis`
- `neo4j`
- `qdrant`
- `event_bus`
- `worker_manager`
- `scheduler`
- `skill_loader`
- `mcp_loader`

这点很重要，因为 Phase 7 之后，系统健康已经不只是“数据库通不通”，而是“扩展系统有没有加载成功”。

### 10.3 启动脚本

新增了：

- [start.ps1](/C:/Users/IVES/Documents/Code/Projects/Mirror/start.ps1)
- [start.sh](/C:/Users/IVES/Documents/Code/Projects/Mirror/start.sh)

脚本做的事情基本一致：

1. 读取 `.env`
2. 检查依赖命令
3. `docker compose up -d`
4. 如本机有 `opencode` 命令则启动本地服务
5. 启动 `uvicorn app.main:app`

这说明 Phase 7 也顺手把“如何启动整套环境”标准化了。

---

## 11. 启动流程

### 11.1 新的装配顺序

Phase 7 的 bootstrap 顺序大致是：

```python
# 1. 初始化存储与基础设施
task_store = TaskStore()
outbox_store = OutboxStore()
idempotency_store = IdempotencyStore()
evolution_journal = EvolutionJournal()
redis_client = Redis.from_url(...)

# 2. 初始化核心能力
model_registry = ModelProviderRegistry(...)
core_memory_store = CoreMemoryStore()
core_memory_cache = CoreMemoryCache(...)
graph_store = GraphStore()
vector_retriever = VectorRetriever(...)

# 3. 初始化后台链路
event_bus = RedisStreamsEventBus(...)
task_system = TaskSystem(...)
blackboard = Blackboard(...)
outbox_relay = OutboxRelay(...)
task_monitor = TaskMonitor(...)

# 4. 初始化进化能力
core_memory_scheduler = CoreMemoryScheduler(...)
personality_evolver = PersonalityEvolver(...)
observer = ObserverEngine(...)
reflector = MetaCognitionReflector(...)
...

# 5. 注册 builtins
builtins = register_builtin_tools(tool_registry)

# 6. 初始化前台链路
soul_engine = SoulEngine(..., tool_registry=tool_registry, hook_registry=hook_registry)
action_router = ActionRouter(..., tool_registry=tool_registry, hook_registry=hook_registry)

# 7. 注册 builtin agents
agent_registry.register(CodeAgent(...), source="builtin")
agent_registry.register(WebAgent(...), source="builtin")

# 8. 加载 local skills
skill_summary = skill_loader.load_all()

# 9. 加载 MCP tools
mcp_summary = await mcp_adapter.load_all()

# 10. 基于 agent_registry 构造 worker_manager
worker_manager = TaskWorkerManager([...])
```

### 11.2 关键变化

启动链路相比之前最大的不同是：

- registry 和 loader 已经成为 bootstrap 的正式阶段
- 不是所有能力都在代码里手工实例化
- runtime 构建结果开始依赖“本地配置 + manifest + 外部 MCP”

这正是“扩展系统”成立的标志。

---

## 12. 优雅降级策略

### 12.1 降级矩阵

| 组件不可用 | 降级行为 |
|-----------|---------|
| `skills/` 目录缺失 | 记为 skipped，应用继续启动 |
| 单个 skill manifest 非法 | 该项 failed，其余 manifest 继续加载 |
| MCP server 不可达或返回非法结果 | 该 server failed，其余 server 继续加载 |
| 工具调用解析失败 | `tool_call` 降级为说明性 direct reply |
| 工具未注册 / 调用失败 | 返回解释性文本，不打断前台主链路 |

### 12.2 关键理解

Phase 7 的扩展层明显贯彻了一个原则：

- 核心运行时优先存活
- 扩展尽量加载
- 单点扩展失败必须可隔离

也就是说，扩展系统是“外挂式增强”，不是“强耦合前置条件”。

---

## 13. 验收标准

### 13.1 验收命令

```bash
python -m compileall app

python -c "from app.main import app; print(app.title)"

python -c "from app.runtime.bootstrap import bootstrap_runtime"
```

### 13.2 验收检查项

- [ ] `app/main.py` 只保留 FastAPI 入口与聚合 `/health`
- [ ] `bootstrap_runtime()` 能完整装配运行时
- [ ] `ToolRegistry.describe_tools()` 能输出结构化工具描述
- [ ] `ToolRegistry.invoke()` 能统一调用 builtin / skill / MCP 工具
- [ ] `HookRegistry.trigger()` 不会因 hook 异常打断主链路
- [ ] `AgentRegistry` 支持 `source` 与 `overwrite`
- [ ] `SkillLoader` 能加载本地 `tool` / `hook` / `sub_agent` manifest
- [ ] `MCPToolAdapter` 能完成 `tools/list` 和 `tools/call` 转发
- [ ] `tool_call` Action 真正走 `ToolRegistry.invoke()`
- [ ] `/health` 能返回扩展层子系统状态

---

## 附：Explicitly Not Done Yet

以下能力在 Phase 7 中**仍未完成**：

- [ ] 更完整的 MCP 认证、会话协商和长连接管理
- [ ] 多步工具规划循环，而不仅是一跳 `tool_call`
- [ ] 远端 skill 市场、热加载、热卸载
- [ ] 启动后新增 agent 时的 worker 动态刷新

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-5-学习笔记]] — Sub-Agent 异步执行
- [[Phase-6-学习笔记]] — 异步进化层
- [[../phase_7_status.md|phase_7_status.md]] — Phase 7 给 Codex 的状态文档
