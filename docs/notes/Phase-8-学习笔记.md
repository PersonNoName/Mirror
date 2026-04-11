# Phase 8 学习笔记：编码与文本完整性

> **前置阶段**：[[Phase-7-学习笔记]]  
> **目标**：规范化系统中的关键文本，清除乱码（mojibake）字符，统一字符编码处理，建立文本完整性基线  
> **里程碑**：本阶段完成后系统文本处理具备稳定的基础设施，避免编码问题回归

---

## 目录

- [概述](#概述)
- [1. Phase 8 文件清单](#1-phase-8-文件清单)
- [2. Phase 8 解决的问题](#2-phase-8-解决的问题)
- [3. 文本规范化策略](#3-文本规范化策略)
- [4. 关键文件修改](#4-关键文件修改)
- [5. 降级规则](#5-降级规则)
- [6. 验证与验收](#6-验证与验收)
- [7. Phase 8 设计原则](#7-phase-8-设计原则)
- [8. Explicitly Not Done Yet](#8-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 8 的目标**不是新增功能**，而是**修复文本完整性问题**。

随着系统多语言处理的复杂度上升，代码中开始出现：

- 乱码（mojibake）字符
- 损坏的字符串字面量
- 非 UTF-8 编码的文本片段
- 用户可见字符串和机器可读提示文本混杂

这些问题如果不解决，会导致：

- 跨平台部署时文本显示异常
- 模型输出受到污染字符影响
- 调试和日志可读性下降
- 未来扩展引入更多编码回归风险

### Phase 8 解决的核心问题

- 替换 `app/soul/engine.py`、`app/soul/router.py`、`app/agents/code_agent.py`、`app/agents/web_agent.py` 中的乱码字面量
- 规范化 `app/tasks/worker.py` 中的异步任务通知文本
- 将机器面向的 prompt 内容转换为稳定英文
- 修复 `CodeAgent` 和 `WebAgent` 的 schema 描述和任务 prompt 文本
- 修复两个 Agent 的 capability keyword 启发式（使用有效的双语关键词）
- 创建 `SOURCE_ENCODING.md` 作为仓库级编码规范

### 重要设计决策

Phase 8 故意聚焦于文本完整性，而非功能扩展：

- 用户可见字符串规范化到稳定英文（降低编码风险）
- 机器面向提示优先使用英文（减少未来编码回归）
- OpenCode 路由兼容性检查不作为扩展 agent 行为的理由

---

## 1. Phase 8 文件清单

| 文件 | 内容 |
|------|------|
| `app/soul/engine.py` | 规范化 prompt 关键文本，转换为稳定英文 |
| `app/soul/router.py` | 规范化 router 文本，处理降级消息 |
| `app/agents/code_agent.py` | 修复 schema 描述、task prompt、capability keywords |
| `app/agents/web_agent.py` | 修复 capability keywords，修复 placeholder 状态文本 |
| `app/tasks/worker.py` | 规范化异步任务通知文本 |
| `SOURCE_ENCODING.md` | 仓库级编码规范文档 |

---

## 2. Phase 8 解决的问题

### 2.1 乱码字符问题

代码库中存在被损坏的字符串字面量，这些字符在多轮编辑或跨平台传输中损坏。典型问题：

- 非 ASCII 字符被错误解码后显示为乱码
- 转义序列不完整导致显示异常
- 手动编辑时输入法切换引入的隐藏字符

Phase 8 的处理方式：

- 替换为稳定可读的英文原文
- 确保字符串在 UTF-8 环境下正确显示
- 避免重新引入损坏字符

### 2.2 双语关键词启发式损坏

`CodeAgent` 和 `WebAgent` 的 capability 判断使用了关键词匹配，但关键词列表本身已损坏：

- 部分关键词变成乱码
- 部分关键词混合了无效字符
- 导致模型无法正确判断 agent 能力

Phase 8 修复为有效的双语（中英文）关键词列表。

### 2.3 机器 vs 用户文本混杂

系统中存在两类不同性质的文本：

- **用户面向**：最终展示给用户的字符串，需要友好、可本地化
- **机器面向**：给模型阅读的 prompt，需要稳定、纯英文、无编码风险

两类文本的编码策略在 Phase 8 前是混乱的。Phase 8 明确了分层策略。

---

## 3. 文本规范化策略

### 3.1 编码规范来源

`SOURCE_ENCODING.md` 是整个仓库的编码规则文档，规定了：

- 所有源代码文件必须使用 UTF-8 编码
- 字符串字面量避免使用非 ASCII 字符（用户面向文本除外）
- 模型 prompt 统一使用英文
- 禁止在代码中硬编码可能损坏的字符

### 3.2 文本分层

Phase 8 建立了两层文本模型：

**用户面向文本**：

- 最终展示给用户
- 可以使用多语言
- 需要友好、可读

**机器面向文本**：

- 嵌入 prompt 供模型阅读
- 统一使用稳定英文
- 避免编码风险

### 3.3 规范化原则

| 场景 | 处理方式 |
|------|---------|
| 用户可见错误消息 | 保持可读英文或中文 |
| 模型 prompt 文本 | 统一使用英文 |
| schema descriptions | 转换为稳定英文 |
| capability keywords | 使用有效双语关键词 |
| 乱码字面量 | 直接替换为清晰英文原文 |

---

## 4. 关键文件修改

### 4.1 `app/soul/engine.py`

SoulEngine 是前台推理的核心组件。Phase 8 修改了其中机器面向的 prompt 文本：

- 替换损坏的字符串字面量
- 将 prompt 内容转换为稳定英文
- 确保文本不会在传输中引入编码问题

### 4.2 `app/soul/router.py`

ActionRouter 负责 action 路由和降级处理。Phase 8 规范化了：

- 降级说明文本
- 错误消息文本
- 保持可读性的同时确保编码稳定

### 4.3 `app/agents/code_agent.py`

CodeAgent 的修改涉及多个层面：

**Schema 描述修复**：

- 原本损坏的 schema 字符串被替换为完整英文描述
- 确保 JSON Schema 本身格式正确

**Task Prompt 文本修复**：

- 替换乱码字面量
- 使用稳定英文重写

**Capability Keywords 修复**：

```python
# 修复前：关键词列表部分损坏
keywords = ["pytho", "vscode", "git", ...]  # 部分关键词已损坏

# 修复后：使用有效双语关键词
keywords = [
    "python", "py", "python3",  # English
    "代码", "编程", "开发",      # 中文
    "vscode", "ide", "编辑器",   # Tools
    ...
]
```

### 4.4 `app/agents/web_agent.py`

WebAgent 的修改与 CodeAgent 类似：

- 修复 capability keyword 启发式
- 替换 placeholder 执行状态的损坏文本
- 明确报告 placeholder 状态，而非使用假的成功文本

### 4.5 `app/tasks/worker.py`

Worker 处理异步任务通知。Phase 8 规范化了：

- 任务状态通知文本
- 异步消息的格式化字符串
- 确保通知文本稳定可读

---

## 5. 降级规则

Phase 8 明确了以下降级规则，这些规则在 Phase 8 之前的实现中是模糊的：

### 5.1 推理模型 API Key 缺失

```
如果：SoulEngine 无法访问推理模型
那么：返回稳定的 fallback 直接回复
```

这个降级避免了模型 API 不可用时系统完全崩溃。

### 5.2 Tool-Call Payload 格式错误

```
如果：模型输出的 tool_call action 的 JSON 解析失败
那么：ActionRouter 返回可读的 fallback 说明
```

### 5.3 WebAgent Placeholder 执行

```
如果：用户触发了 placeholder WebAgent 执行
那么：WebAgent 明确报告 placeholder 状态
    而非返回损坏的假成功文本
```

这让用户知道当前是占位实现，而不是被虚假成功误导。

---

## 6. 验证与验收

### 6.1 验证命令

```bash
# Python 语法检查
python -m compileall app

# 应用启动验证
python -c "from app.main import app; print(app.title)"

# 乱码扫描
# 在 app/**/*.py 中搜索常见乱码标记，返回无匹配
```

### 6.2 验收检查项

- [ ] `app/soul/engine.py` 中无乱码字符
- [ ] `app/soul/router.py` 中无乱码字符
- [ ] `app/agents/code_agent.py` 中 schema 描述完整可读
- [ ] `app/agents/code_agent.py` 中 capability keywords 有效
- [ ] `app/agents/web_agent.py` 中 capability keywords 有效
- [ ] `app/tasks/worker.py` 中无乱码字符
- [ ] `SOURCE_ENCODING.md` 存在并描述编码规范
- [ ] `python -m compileall app` 通过
- [ ] `python -c "from app.main import app"` 通过

### 6.3 明确不会做的事

Phase 8 **不会**做以下事情：

- 完整的仓库级损坏遗留规划文档规范化
- 用真正的网页执行替换占位符 WebAgent
- 运行时失败语义强化（事件总线、worker 重试路径）
- 自动化测试

---

## 7. Phase 8 设计原则

### 7.1 稳定胜于功能

Phase 8 体现了"先稳定再扩展"的思想：

- 系统能跑不代表文本处理没问题
- 乱码可能在特定条件下触发模型异常输出
- 规范化文本是后续多语言支持的基础

### 7.2 机器面向文本优先英文

这个决策的理由是：

- 英文 prompt 更稳定（减少字符集问题）
- 模型训练数据以英文为主
- 避免非 ASCII 字符在 prompt 中引发意外行为

### 7.3 不扩展功能

Phase 8 故意保持边界清晰：

- 看见了 OpenCode 文档，但只做兼容性检查
- 不因为参考实现就扩展 agent 行为
- 专注于文本问题，不引入新功能

---

## 8. Explicitly Not Done Yet

以下功能在 Phase 8 中**仍未完成**：

- [ ] 完整的仓库级规范化（损坏的遗留规划文档）
- [ ] 真正的 WebAgent 网页执行实现
- [ ] 事件总线的运行时失败语义强化
- [ ] Worker 重试路径的运行时失败语义强化
- [ ] 自动化测试覆盖

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-7-学习笔记]] — 扩展注册表与集成层
- [[../phase_8_status.md|phase_8_status.md]] — Phase 8 给 Codex 的状态文档
- [[../SOURCE_ENCODING.md|SOURCE_ENCODING.md]] — 仓库编码规范
