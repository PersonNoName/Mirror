# Phase 9 学习笔记：测试基础与安全网

> **前置阶段**：[[Phase-8-学习笔记]]  
> **目标**：建立本地自动化测试基础设施，为后续 phases 提供回归安全网  
> **里程碑**：本阶段完成后系统具备本地快速测试能力，无需依赖外部服务

---

## 目录

- [概述](#概述)
- [1. Phase 9 文件清单](#1-phase-9-文件清单)
- [2. 为什么 Phase 9 是测试基础](#2-为什么-phase-9-是测试基础)
- [3. 测试框架配置](#3-测试框架配置)
- [4. 测试设计与隔离策略](#4-测试设计与隔离策略)
- [5. 测试覆盖范围](#5-测试覆盖范围)
- [6. 验证与验收](#6-验证与验收)
- [7. 设计原则](#7-设计原则)
- [8. Explicitly Not Done Yet](#8-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 9 的目标是**建立测试基础设施**，为整个项目提供回归安全网。

Phase 8 修复了文本完整性问题，Phase 9 则在此基础上建立验证机制：

- 确保已修复的文本问题不会在未来版本中回归
- 确保核心组件（Engine、Router、Registry）行为符合预期
- 确保 bootstrap 流程能在降级模式下正常启动

### Phase 9 解决的核心问题

- 测试框架缺失（无 `pytest` 相关配置）
- 核心组件没有自动化测试覆盖
- Bootstrap 流程没有烟雾测试
- 所有测试依赖外部服务（Redis、PostgreSQL 等）

### 新的系统形态

Phase 9 之后，开发工作流变为：

```text
代码修改
    ↓
本地运行 pytest
    ↓
24 个测试通过
    ↓
验证无回归
    ↓
继续开发或提交
```

---

## 1. Phase 9 文件清单

| 文件 | 内容 |
|------|------|
| `requirements.txt` | 新增 `pytest`、`pytest-asyncio` 依赖 |
| `pytest.ini` | pytest 配置文件 |
| `tests/` 目录 | 测试包，含 fixtures 和 Helpers |
| `tests/test_soul_engine.py` | SoulEngine 单元测试 |
| `tests/test_action_router.py` | ActionRouter 单元测试 |
| `tests/test_tool_registry.py` | ToolRegistry.invoke 单元测试 |
| `tests/test_task_system.py` | TaskSystem HITL 等待/响应流程测试 |
| `tests/test_web_platform_adapter.py` | WebPlatformAdapter 单元测试 |
| `tests/test_bootstrap_smoke.py` | bootstrap_runtime 降级模式烟雾测试 |

---

## 2. 为什么 Phase 9 是测试基础

### 2.1 Phase 8 之后的工程需求

Phase 8 修复了文本完整性问题，但如果未来有人引入新的乱码字符或修改了关键组件，没有机制来防止回归。

测试基础设施的价值：

- **快速反馈**：修改代码后立即知道是否破坏已有功能
- **回归保护**：防止已修复的问题重新出现
- **文档作用**：测试本身就是组件行为的文档

### 2.2 本地优先策略

Phase 9 明确了一个重要原则：**本地优先，依赖无关**。

这意味着：

- 测试不依赖 Redis、PostgreSQL、Neo4j、Qdrant 等外部服务
- 不依赖 OpenCode 服务器
- 所有外部依赖使用 stub 或 monkeypatch

这样做的好处：

- Windows 环境可直接运行（无需配置复杂的服务栈）
- CI 之前可先在本地验证
- 测试执行速度快

### 2.3 从 Phase 6-8 学到的

Phase 6-8 已经展示了降级设计的重要性。测试基础设施也遵循同样原则：

- 外部服务不可用 -> 测试使用 stub
- 某项测试失败 -> 不阻塞其他测试
- 本地测试优先 -> 不强依赖 CI 环境

---

## 3. 测试框架配置

### 3.1 依赖项

`requirements.txt` 新增：

```text
pytest
pytest-asyncio
```

### 3.2 pytest.ini 配置

```ini
[pytest]
asyncio_mode = auto
cache_provider = none
```

关键配置说明：

- `asyncio_mode = auto`：自动识别 async 测试函数
- `cache_provider = none`：禁用缓存提供器，避免 Windows 权限问题

### 3.3 测试目录结构

```
tests/
    __init__.py
    conftest.py          # fixtures 和 helpers
    test_soul_engine.py
    test_action_router.py
    test_tool_registry.py
    test_task_system.py
    test_web_platform_adapter.py
    test_bootstrap_smoke.py
```

---

## 4. 测试设计与隔离策略

### 4.1 测试隔离原则

Phase 9 的测试完全隔离于外部服务：

```
测试运行
    ↓
不连接真实 Redis
    ↓
不连接真实 PostgreSQL
    ↓
不连接真实 Neo4j / Qdrant
    ↓
不调用真实 OpenCode API
```

### 4.2 Monkeypatch 和 Stub 策略

对于需要外部依赖的测试组件，使用：

- **Monkeypatched 构造函数**：替换真实类为 Stub 类
- **Stub 组件**：实现最小接口的假组件
- **降级模式 bootstrap**：模拟组件不可用的场景

```python
# 示例：降级模式 bootstrap 烟雾测试
def test_bootstrap_smoke():
    # monkeypatch 外部服务构造函数
    with monkeypatch_redis(), monkeypatch_postgres():
        runtime = bootstrap_runtime()
        assert runtime is not None
```

### 4.3 pytest-asyncio 异步支持

```python
@pytest.mark.asyncio
async def test_soul_engine_run():
    ...
```

`asyncio_mode = auto` 使 pytest 自动识别 async 测试函数，无需手动标记。

---

## 5. 测试覆盖范围

### 5.1 SoulEngine 测试

覆盖：

- `run()` 基本执行路径
- 降级模式下的 fallback 行为
- Prompt 文本完整性（确保无乱码）

### 5.2 ActionRouter 测试

覆盖：

- `route()` 路由分发
- `tool_call` action 的解析和调用
- 降级路径（payload 解析失败、工具未注册等）

### 5.3 ToolRegistry.invoke 测试

覆盖：

- 工具注册和调用
- 参数传递
- 异常处理和降级

### 5.4 TaskSystem HITL 测试

覆盖：

- HITL 等待流程
- 用户反馈响应流程
- 超时降级

### 5.5 WebPlatformAdapter 测试

覆盖：

- 平台适配的基本接口
- 降级行为

### 5.6 Bootstrap 烟雾测试

覆盖：

- 降级模式下 `bootstrap_runtime()` 能正常返回
- 核心组件能正确实例化
- 不会因缺少外部服务而崩溃

### 5.7 测试数量

```
pytest 结果：24 passed
```

24 个测试覆盖了核心组件的基本路径。

---

## 6. 验证与验收

### 6.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 6.2 验收检查项

- [ ] `pytest` 能正常执行
- [ ] 24 个测试全部通过
- [ ] 测试不依赖真实 Redis
- [ ] 测试不依赖真实 PostgreSQL
- [ ] 测试不依赖真实 Neo4j / Qdrant
- [ ] `python -m compileall app tests` 通过
- [ ] Bootstrap 烟雾测试通过

### 6.3 明确不会做的事

Phase 9 **不会**做以下事情：

- 集成测试（依赖真实外部服务）
- 端到端流程测试（chat/task/HITL 完整链路）
- CI pipeline 配置
- Phase 10 的运行时失败语义强化
- Phase 12 的 WebAgent 真实执行替换

---

## 7. 设计原则

### 7.1 本地优先

Phase 9 强调测试应该在本地可快速运行：

- 不需要启动 Docker 服务
- 不需要配置外部数据库
- 不需要连接远程 API

### 7.2 扩展优于重复

测试设计遵循一个原则：**扩展现有测试文件，而非创建冗余新套件**。

如果需要测试新功能，优先：

1. 找到现有的相关测试文件
2. 在其中添加新测试
3. 避免创建只有 2-3 个测试的新文件

### 7.3 安全网而非质量认证

测试基础设施是"安全网"，不是"质量认证"：

- 通过测试 ≠ 代码质量完美
- 未通过测试 = 很可能有问题
- 测试是最低保证，不是完整验证

---

## 8. Explicitly Not Done Yet

以下功能在 Phase 9 中**仍未完成**：

- [ ] 集成测试（针对真实 Redis、PostgreSQL、Neo4j、Qdrant）
- [ ] 端到端 chat/task/HITL 流程测试
- [ ] CI pipeline 配置
- [ ] Phase 10 的运行时失败语义强化
- [ ] Phase 12 的 WebAgent 真实执行

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-8-学习笔记]] — 编码与文本完整性
- [[../phase_9_status.md|phase_9_status.md]] — Phase 9 给 Codex 的状态文档
