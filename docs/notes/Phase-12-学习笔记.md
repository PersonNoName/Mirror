# Phase 12 学习笔记：WebAgent 真实搜索实现

> **前置阶段**：[[Phase-11-学习笔记]]  
> **目标**：将占位符 WebAgent 替换为有边界的最小可用水搜索实现  
> **里程碑**：本阶段完成后 WebAgent 具备真实搜索能力，返回可验证的结果而非假成功文本

---

## 目录

- [概述](#概述)
- [1. Phase 12 文件清单](#1-phase-12-文件清单)
- [2. 为什么需要真实搜索](#2-为什么需要真实搜索)
- [3. 搜索实现设计](#3-搜索实现设计)
- [4. 查询派生与边界](#4-查询派生与边界)
- [5. HTML 提取与清洗](#5-html-提取与清洗)
- [6. 结构化输出](#6-结构化输出)
- [7. 失败语义细化](#7-失败语义细化)
- [8. Capability 诚实估计](#8-capability-诚实估计)
- [9. 验证与验收](#9-验证与验收)
- [10. 设计原则](#10-设计原则)
- [11. Explicitly Not Done Yet](#11-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 12 的目标是**将 WebAgent 从占位符升级为真实搜索实现**。

Phase 8-11 解决了文本完整性、测试基础设施、失败语义、可观测性问题。Phase 12 则利用这些基础设施，实现了真正可用的网页搜索。

### Phase 11 到 Phase 12 的演进

Phase 11 的 WebAgent 还是占位符：

- 用户请求网页搜索时，返回"这是占位实现"的假成功文本
- 没有真正的网络请求
- 无法验证搜索结果

Phase 12 实现了：

- 真实搜索查询到 DuckDuckGo HTML
- 提取搜索结果中的 URL
- 获取并解析结果页面
- 返回结构化、可验证的结果

### 新的系统形态

```
WebAgent.execute()
    ↓
┌─ 派生查询 ─────────────────┐
│ intent + prompt_snapshot     │
│ 截断到有限长度               │
└────────────────────────────┘
    ↓
┌─ 搜索 ─────────────────────┐
│ DuckDuckGo HTML search      │
│ 无 JS 渲染                  │
│ 无认证                      │
└────────────────────────────┘
    ↓
┌─ 结果提取 ─────────────────┐
│ 最多 3 个结果页面           │
│ HTML 转文本                │
│ 去除 script/style          │
└────────────────────────────┘
    ↓
┌─ 结构化输出 ──────────────┐
│ summary / query / sources  │
│ snippets                   │
│ 真实结果或诚实无结果       │
└────────────────────────────┘
```

---

## 1. Phase 12 文件清单

| 文件 | 内容 |
|------|------|
| `app/agents/web_agent.py` | 完整重写 `execute()`，实现真实搜索 |
| `tests/test_web_agent.py` | WebAgent 专项测试 |

---

## 2. 为什么需要真实搜索

### 2.1 占位符的问题

Phase 8 建立的文本完整性修复了 WebAgent 的乱码文本，但 WebAgent 本身还是占位符：

- 用户请求搜索时，返回假成功文本
- 用户无法获得真实信息
- 系统行为不诚实

### 2.2 真实搜索的价值

实现真实搜索后：

- 用户请求有实际效果
- 返回结果可验证
- 错误处理有实际意义
- 失败语义（Phase 10）能真正保护系统

### 2.3 最小可行搜索

Phase 12 不是要实现完整的浏览器自动化，而是"最小可行搜索"：

- 单一查询派生
- DuckDuckGo HTML 搜索
- 最多 3 个结果页面
- 有限超时
- 纯 HTML 提取

---

## 3. 搜索实现设计

### 3.1 选择 DuckDuckGo HTML

Phase 12 选择 DuckDuckGo HTML 搜索作为实现源，原因：

| 特性 | 说明 |
|------|------|
| 无需认证 | 不需要 API key 或登录 |
| HTML 响应 | 直接解析，无需 JavaScript 渲染 |
| 无浏览器自动化 | 不需要 Selenium/Playwright |
| 适合简单查询 | 适合一次性搜索场景 |

### 3.2 为什么不选择其他方案

| 方案 | 为什么不选 |
|------|----------|
| Google Search API | 需要 API key，有配额限制 |
| Selenium/Playwright | 复杂，资源消耗大 |
| 直接爬虫 | 需要处理 robots.txt、IP 限制等 |
| 认证会话 | 超出 Phase 12 范围 |

### 3.3 搜索边界

```python
MAX_RESULTS = 3
MAX_QUERY_LENGTH = 200
FETCH_TIMEOUT_SECONDS = 10
```

这些边界确保：

- 搜索不会无限放大
- 资源消耗可控
- 系统不会被单个搜索请求拖垮

---

## 4. 查询派生与边界

### 4.1 查询派生策略

```python
def _derive_query(intent: str, prompt_snapshot: str) -> str:
    query = f"{intent} {prompt_snapshot}"
    return query[:MAX_QUERY_LENGTH]
```

查询派生策略**刻意简单**：

- 拼接 `intent` 和 `prompt_snapshot`
- 截断到最大长度

### 4.2 为什么简单

Phase 12 不实现复杂查询理解，因为：

- 复杂查询理解需要更多模型调用
- Phase 12 目标是"可工作"而非"完美"
- 简单策略在大多场景下足够好

### 4.3 边界限制

| 边界 | 值 | 目的 |
|------|-----|------|
| `MAX_QUERY_LENGTH` | 200 | 防止超长查询 |
| `MAX_RESULTS` | 3 | 限制资源消耗 |
| `FETCH_TIMEOUT_SECONDS` | 10 | 防止单请求挂起 |

---

## 5. HTML 提取与清洗

### 5.1 提取策略

Phase 12 使用纯 HTML 提取，不执行 JavaScript：

```python
def _extract_text_from_html(html: str) -> str:
    # 去除 script 和 style
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
    
    # 去除所有 HTML 标签
    html = re.sub(r'<[^>]+>', '', html)
    
    # 规范化空白
    html = re.sub(r'\s+', ' ', html)
    
    return html.strip()
```

### 5.2 清洗步骤

| 步骤 | 说明 |
|------|------|
| 去除 `<script>` | 移除 JavaScript 代码 |
| 去除 `<style>` | 移除 CSS 样式 |
| 去除所有标签 | 提取纯文本 |
| 规范化空白 | 合并多余空格 |

### 5.3 不做什么

Phase 12 **不实现**：

- CSS 布局分析
- 语义 HTML 解析
- JavaScript 执行
- 动态内容加载

---

## 6. 结构化输出

### 6.1 输出格式

Phase 12 的 WebAgent 输出是**结构化**的：

```python
{
    "summary": "...",      # 搜索结果摘要
    "query": "...",        # 实际使用的查询
    "sources": [...],      # 来源 URL 列表
    "snippets": [...]      # 每个来源的片段
}
```

### 6.2 诚实输出

Phase 12 强调**诚实输出**：

- 有结果 → 返回真实摘要和来源
- 无结果 → 返回"未找到"的诚实说明
- 部分失败 → 跳过失败页面，返回剩余结果

### 6.3 失败 vs 成功

| 场景 | 结果 |
|------|------|
| 搜索成功，有结果 | `done` + 结构化结果 |
| 搜索成功，无结果 | `done` + 诚实无结果说明 |
| 网络超时/瞬态错误 | `failed` + `error_type=RETRYABLE` |
| HTTP 非 2xx 错误 | `failed` + `error_type=FATAL` |
| 单页面获取失败 | **跳过**该页面，继续其他页面 |

### 6.4 部分失败处理

```python
successful_snippets = []
failed_urls = []

for url in urls[:MAX_RESULTS]:
    try:
        content = await fetch_url(url)
        snippets.append(...)
    except FetchTimeoutError:
        failed_urls.append(url)
        continue  # 跳过，不中止整个任务
```

这确保单个页面失败不会导致整个搜索任务失败。

---

## 7. 失败语义细化

### 7.1 失败分类

Phase 12 细化了 WebAgent 的失败语义：

| 错误类型 | 场景 | 结果状态 | error_type |
|---------|------|---------|------------|
| **RETRYABLE** | 网络超时、DNS 临时失败 | `failed` | `RETRYABLE` |
| **FATAL** | HTTP 4xx/5xx、非 HTTP 协议错误 | `failed` | `FATAL` |
| **ZERO_MATCHES** | 搜索返回 0 结果 | `done` | - |

### 7.2 RETRYABLE vs FATAL

```python
if isinstance(e, (asyncio.TimeoutError, ConnectionError)):
    error_type = "RETRYABLE"  # 网络问题，可能重试成功
elif isinstance(e, HTTPError):
    error_type = "FATAL"  # 服务器明确拒绝，不再重试
```

区分意义：

- `RETRYABLE` 错误可能在稍后重试成功
- `FATAL` 错误重试无意义

### 7.3 ZERO_MATCHES 处理

```python
if len(results) == 0:
    return {
        "status": "done",
        "summary": "No search results found for the query.",
        "query": query,
        "sources": [],
        "snippets": [],
    }
```

这是 Phase 12"诚实输出"原则的体现：

- 不假装有结果
- 明确告知用户未找到

---

## 8. Capability 诚实估计

### 8.1 之前的问题

Phase 8-11 的 `WebAgent.estimate_capability()` 没有反映真实能力：

- 声称支持复杂网页交互
- 声称支持 JavaScript 渲染页面
- 关键词列表不准确

### 8.2 Phase 12 的诚实化

```python
SUPPORTED_SCOPE = [
    "search",
    "docs_lookup",
    "page_retrieval",
    "source_collection",
]

UNSUPPORTED_SCOPE = [
    "browser_automation",
    "javascript_rendering",
    "form_submission",
    "authenticated_sessions",
]
```

### 8.3 关键词评分清理

Phase 8 的 capability keywords 修复被保留并进一步清理：

```python
CAPABILITY_KEYWORDS = {
    "web_search": ["search", "查询", "搜索", "look up", "find online"],
    "docs_lookup": ["documentation", "docs", "手册", "reference"],
    "page_retrieval": ["open", "fetch", "retrieve", "访问", "获取页面"],
}
```

---

## 9. 验证与验收

### 9.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 9.2 验收检查项

- [ ] 43 个测试全部通过（Phase 11 的 37 + Phase 12 新增）
- [ ] WebAgent 能执行真实搜索
- [ ] WebAgent 返回结构化输出（summary/query/sources/snippets）
- [ ] 无结果时返回诚实说明
- [ ] 网络超时返回 `RETRYABLE` 失败
- [ ] HTTP 错误返回 `FATAL` 失败
- [ ] 单页面失败跳过，不中止整个任务
- [ ] 最多获取 3 个结果页面
- [ ] HTML 提取去除 script/style/标签
- [ ] `estimate_capability()` 反映真实支持范围

### 9.3 明确不会做的事

Phase 12 **不会**做以下事情：

- 浏览器自动化
- JavaScript 渲染页面支持
- 分页爬取
- 域名礼貌策略、robots.txt 处理、速率限制
- 更丰富的结果排序或摘要模型处理
- 认证网页会话或 cookie 持久化

---

## 10. 设计原则

### 10.1 诚实输出

Phase 12 最重要的原则是**诚实输出**：

- 不返回假成功
- 不隐瞒失败
- 明确说明系统能力边界

### 10.2 有界实现

搜索实现有明确的边界：

- 单一查询
- 最多 3 个结果
- 有限超时
- 纯 HTML 提取

这些边界确保 Phase 12 不会引入复杂性蔓延。

### 10.3 部分失败容忍

单个页面失败**跳过**而非中止：

- 提高整体成功率
- 返回部分结果比完全无结果好
- 符合 Phase 10 的失败语义设计

### 10.4 检索而非自动化

WebAgent 被明确定位为**检索工具**：

- 检索：搜索、获取页面、提取内容
- 不是：浏览器自动化、表单提交、会话管理

---

## 11. Explicitly Not Done Yet

以下功能在 Phase 12 中**仍未完成**：

- [ ] 浏览器自动化
- [ ] JavaScript 渲染页面支持
- [ ] 分页爬取
- [ ] 域名礼貌策略、robots.txt 处理、速率限制
- [ ] 更丰富的结果排序或摘要模型处理
- [ ] 认证网页会话或 cookie 持久化

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-11-学习笔记]] — 可观测性与运维清晰度
- [[../phase_12_status.md|phase_12_status.md]] — Phase 12 给 Codex 的状态文档
