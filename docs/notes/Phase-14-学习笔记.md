# Phase 14 学习笔记：API 与产品表面清理

> **前置阶段**：[[Phase-13-学习笔记]]  
> **目标**：清理和规范化公开 API 契约，建立统一的响应模型和错误封装，提升 API 的可预测性和可维护性  
> **里程碑**：本阶段完成后所有公开 API 端点使用类型化响应模型，错误处理一致，公开 payload 不再泄露内部实现细节

---

## 目录

- [概述](#概述)
- [1. Phase 14 文件清单](#1-phase-14-文件清单)
- [2. 为什么需要 API 清理](#2-为什么需要-api-清理)
- [3. 共享 API 模型](#3-共享-api-模型)
- [4. 请求验证强化](#4-请求验证强化)
- [5. 类型化响应模型](#5-类型化响应模型)
- [6. 标准错误封装](#6-标准错误封装)
- [7. `/chat` 公开契约收窄](#7-chat-公开契约收窄)
- [8. `/chat/stream` SSE 保持稳定](#8-chatstream-sse-保持稳定)
- [9. Journal 响应类型化](#9-journal-响应类型化)
- [10. 验证与验收](#10-验证与验收)
- [11. 设计原则](#11-设计原则)
- [12. Explicitly Not Done Yet](#12-explicitly-not-done-yet)

---

## 概述

### 目标

Phase 14 的目标是**清理 API 与产品表面**，规范化公开契约。

Phase 13 关注了检索和 prompt 生成稳定性，Phase 14 则将注意力转向**对外暴露的 API**——这些是客户端和前端直接依赖的接口。

### Phase 13 到 Phase 14 的演进

Phase 13 之后，API 层面存在以下问题：

1. **响应格式不一致**：
   - 有的端点返回原始字典
   - 有的端点返回类型化模型
   - Pydantic 模型的 datetime 序列化不一致

2. **错误处理不统一**：
   - 不同端点用不同格式返回错误
   - 内部错误（action routing failed）直接暴露给客户端
   - streaming 不可用时的错误格式不明确

3. **公开 payload 泄露内部细节**：
   - `/chat` 响应包含原始 router 结果字典
   - task_id 等内部字段暴露在顶层
   - 客户端能看到不应该看到的实现细节

Phase 14 修复了这些问题。

### 新的系统形态

```
请求 → FastAPI 路由
    ↓
请求验证（Pydantic）
    ↓
业务逻辑
    ↓
类型化响应模型
    ↓
统一的错误封装
    ↓
客户端收到一致格式
```

---

## 1. Phase 14 文件清单

| 文件 | 内容 |
|------|------|
| `app/api/models.py` | 共享 API 响应和错误模型 |
| `app/api/chat.py` | 类型化 `/chat` 响应 |
| `app/api/hitl.py` | 类型化 `/hitl/respond` 响应 |
| `app/api/journal.py` | 类型化 `/evolution/journal` 响应 |
| `tests/test_api_routes.py` | 路由契约测试 |

---

## 2. 为什么需要 API 清理

### 2.1 之前的问题

Phase 14 之前的 API 存在以下问题：

| 问题 | 影响 |
|------|------|
| 响应格式不一致 | 客户端难以可靠地解析 |
| 错误处理混乱 | 错误处理逻辑分散，难以统一处理 |
| 内部细节泄露 | 客户端看到不稳定的内部实现细节 |
| datetime 序列化不统一 | 不同端点返回不同格式的时间字符串 |

### 2.2 API 契约的价值

清晰的 API 契约确保：

- **客户端可预测**：相同端点的响应格式一致
- **版本稳定**：内部变化不影响公开契约
- **错误可处理**：客户端能可靠地识别和处理错误
- **文档友好**：OpenAPI schema 自动准确

### 2.3 公开 vs 内部

Phase 14 明确了**公开契约**和**内部实现**的边界：

- **公开契约**：客户端应该依赖的部分，稳定
- **内部实现**：可能变化的实现细节，不应暴露

---

## 3. 共享 API 模型

### 3.1 `app/api/models.py`

Phase 14 新增了共享的 API 模型定义：

```python
# 响应模型
class ChatResponse(BaseModel):
    reply: str
    session_id: str
    user_id: str
    status: str  # "completed" | "accepted" | "waiting_hitl"
    meta: ChatMeta | None = None

class ChatMeta(BaseModel):
    task_id: str | None = None

# 错误封装
class ErrorEnvelope(BaseModel):
    error: ErrorDetail

class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
```

### 3.2 模型复用

共享模型被多个端点使用：

```python
# /chat 使用 ChatResponse
@app.post("/chat")
async def chat(request: ChatRequest) -> ChatResponse:
    ...

# /hitl/respond 使用 ErrorEnvelope
@app.post("/hitl/respond")
async def hitl_respond(...) -> ChatResponse | ErrorEnvelope:
    ...
```

### 3.3 好处

共享模型的好处：

- **一致性强**：所有端点使用相同的错误格式
- **可复用**：减少重复定义
- **可测试**：可以单独测试模型
- **OpenAPI 友好**：自动生成准确的 schema

---

## 4. 请求验证强化

### 4.1 验证的端点

Phase 14 强化了以下端点的请求验证：

| 端点 | 验证内容 |
|------|---------|
| `/chat` | `user_id`, `session_id`, `message` 必填；长度限制 |
| `/chat/stream` | 同 `/chat` |
| `/hitl/respond` | `task_id`, `feedback` 必填；格式验证 |

### 4.2 Pydantic 验证

使用 Pydantic 进行声明式验证：

```python
class ChatRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=10000)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "user_123",
                "session_id": "session_abc",
                "message": "Hello, help me with coding"
            }
        }
    }
```

### 4.3 FastAPI 422 保留

```python
# FastAPI 默认的 422 行为被保留
# 对于格式错误的输入，返回标准的 422 Unprocessable Entity
```

Phase 14 **不改变** FastAPI 的默认验证错误行为，只在路由自有失败场景添加自定义错误。

---

## 5. 类型化响应模型

### 5.1 `/chat` 响应

Phase 14 之前，`/chat` 直接返回原始字典：

```python
# 之前（不类型化）
return {
    "reply": reply_text,
    "task_id": task_id,  # 内部字段泄露
    "router_result": raw_router_dict,  # 不应该暴露
}
```

Phase 14 之后，使用类型化响应：

```python
# 之后（类型化）
return ChatResponse(
    reply=reply_text,
    session_id=session_id,
    user_id=user_id,
    status=_derive_status(action_type),  # 从内部 action type 派生
    meta=ChatMeta(task_id=task_id) if task_id else None
)
```

### 5.2 Status 派生逻辑

| Action Type | Status |
|-------------|--------|
| `direct_reply` | `completed` |
| `tool_reply` | `completed` |
| `task_dispatch` | `accepted` |
| `hitl_relay` | `waiting_hitl` |

Status 从内部 action type **派生**，而不是直接暴露内部状态。

### 5.3 `/hitl/respond` 响应

```python
class HITLRespondRequest(BaseModel):
    task_id: str = Field(..., min_length=1)
    feedback: str = Field(..., min_length=1, max_length=10000)

class HITLRespondResponse(BaseModel):
    status: str  # "processed" | "error"
    message: str
```

### 5.4 `/evolution/journal` 响应

```python
class JournalEntry(BaseModel):
    id: str
    user_id: str
    event_type: str
    summary: str
    details: dict[str, Any]
    created_at: datetime  # Pydantic 自动处理 datetime 序列化
```

**关键改进**：datetime 序列化不再手写字符串，而是交给 Pydantic/FastAPI 处理。

---

## 6. 标准错误封装

### 6.1 错误封装格式

Phase 14 建立了统一的错误封装格式：

```python
class ErrorEnvelope(BaseModel):
    error: ErrorDetail

class ErrorDetail(BaseModel):
    code: str           # 错误码，如 "ACTION_ROUTING_FAILED"
    message: str        # 人类可读的错误描述
    details: dict | None = None  # 可选的额外信息
```

### 6.2 标准错误码

| 错误码 | 说明 | 触发场景 |
|--------|------|---------|
| `ACTION_ROUTING_FAILED` | Action 路由失败 | ActionRouter 无法处理某个 action |
| `STREAMING_UNAVAILABLE` | 流式传输不可用 | Redis 不可用时调用 `/chat/stream` |
| `TASK_NOT_FOUND` | 任务未找到 | HITL 响应时指定的 task_id 不存在 |

### 6.3 错误响应示例

```json
{
    "error": {
        "code": "ACTION_ROUTING_FAILED",
        "message": "Failed to route the requested action.",
        "details": {
            "action_type": "unknown",
            "original_message": "..."
        }
    }
}
```

### 6.4 不暴露内部错误细节

Phase 14 的一个关键改进是**不将原始异常暴露给客户端**：

```python
# 之前（泄露内部细节）
return {"error": str(e), "traceback": e.__traceback__}

# 之后（安全的错误封装）
logger.exception("Action routing failed")  # 内部记录完整信息
return ErrorEnvelope(error=ErrorDetail(
    code="ACTION_ROUTING_FAILED",
    message="Failed to route the requested action."
))
```

---

## 7. `/chat` 公开契约收窄

### 7.1 之前的问题

Phase 14 之前，`/chat` 的公开响应包含过多内部细节：

```json
{
    "reply": "Hello!",
    "session_id": "abc123",
    "user_id": "user_456",
    "task_id": "task_789",          // 内部字段泄露到顶层
    "router_action_type": "direct", // 不应该暴露
    "internal_metadata": {...}       // 更不应该暴露
}
```

### 7.2 收窄后的公开契约

Phase 14 将内部字段移到 `meta` 下：

```json
{
    "reply": "Hello!",
    "session_id": "abc123",
    "user_id": "user_456",
    "status": "completed",
    "meta": {
        "task_id": "task_789"  // 现在在 meta 下，标记为可选
    }
}
```

### 7.3 公开 vs 内部字段

| 字段 | 位置 | 说明 |
|------|------|------|
| `reply` | 顶层 | 必填，用户面向 |
| `session_id` | 顶层 | 必填，公开 |
| `user_id` | 顶层 | 必填，公开 |
| `status` | 顶层 | 必填，公开 |
| `task_id` | `meta` 下 | 可选，内部链接 |

### 7.4 设计理由

收窄公开契约的好处：

- **稳定性**：内部变化不影响公开契约
- **安全性**：不泄露实现细节
- **可预测性**：客户端只依赖明确公开的字段

---

## 8. `/chat/stream` SSE 保持稳定

### 8.1 保持不变的部分

Phase 14 **保持** `/chat/stream` 的 SSE 传输格式不变：

```python
# SSE 事件格式保持不变
async def event_stream():
    yield {"event": "delta", "data": "Hello"}
    yield {"event": "delta", "data": "!"}
    yield {"event": "done", "data": ""}
```

### 8.2 只改进错误输出

Phase 14 只标准化了 streaming 不可用时的错误输出：

```python
# 之前：不确定的错误格式
return {"error": "streaming disabled"}

# 之后：统一的错误封装
return ErrorEnvelope(error=ErrorDetail(
    code="STREAMING_UNAVAILABLE",
    message="Streaming is currently unavailable."
))
```

### 8.3 Delta / Message / Done 保持不变

| SSE 事件 | 说明 |
|----------|------|
| `delta` | 增量文本输出 |
| `message` | 完整消息（可选） |
| `done` | 流结束信号 |

---

## 9. Journal 响应类型化

### 9.1 之前的问题

```python
# 之前：手写 datetime 序列化
{
    "id": entry.id,
    "created_at": entry.created_at.isoformat(),  # 手写，容易出错
    ...
}
```

### 9.2 之后：Pydantic 处理

```python
class JournalEntry(BaseModel):
    id: str
    user_id: str
    event_type: str
    summary: str
    details: dict[str, Any]
    created_at: datetime  # Pydantic 自动序列化

# 返回时直接用 Pydantic 模型
return JournalEntry(**entry.__dict__)
```

### 9.3 好处

- **一致性**：所有 datetime 使用统一格式
- **可靠性**：不依赖手写序列化逻辑
- **可配置性**：可以在 Pydantic 层面统一配置 datetime 格式

---

## 10. 验证与验收

### 10.1 验证命令

```bash
# 运行所有测试
pytest

# 语法检查
python -m compileall app tests

# 应用启动验证
python -c "from app.main import app; print(app.title)"
```

### 10.2 验收检查项

- [ ] 62 个测试全部通过（Phase 13 的 53 + Phase 14 新增）
- [ ] `/chat` 返回类型化 `ChatResponse` 模型
- [ ] `/chat` 内部字段移到 `meta.task_id` 下
- [ ] `/hitl/respond` 返回类型化响应
- [ ] `/evolution/journal` 返回类型化 `JournalEntry` 列表
- [ ] `ErrorEnvelope` 用于所有自定义错误
- [ ] 标准错误码：`ACTION_ROUTING_FAILED`、`STREAMING_UNAVAILABLE`、`TASK_NOT_FOUND`
- [ ] datetime 序列化由 Pydantic 处理
- [ ] FastAPI 422 保留用于格式错误输入

### 10.3 明确不会做的事

Phase 14 **不会**做以下事情：

- 全局异常中间件
- 版本化 API surface
- 前端特定的流式协议变更
- 更丰富的 async task 生命周期公开元数据
- 认证/授权或 per-user journal 访问策略

---

## 11. 设计原则

### 11.1 公开契约稳定

`/chat` 的公开 payload 应该**保持稳定**：

- 不在顶层暴露内部字段
- 内部字段通过 `meta` 传递
- 客户端只依赖公开契约

### 11.2 错误封装统一

所有路由自有错误使用**统一的错误封装**：

```python
ErrorEnvelope(error=ErrorDetail(code=..., message=..., details=...))
```

不暴露堆栈跟踪或内部异常详情。

### 11.3 类型化优于字典

响应应该使用**类型化模型**而非原始字典：

- 类型检查
- 自动 OpenAPI schema
- IDE 自动补全
- datetime 处理

### 11.4 SSE 稳定

`/chat/stream` 的 SSE 传输格式**保持稳定**：

- 只改进错误输出
- 不改变 delta/message/done 语义
- 不引入新的 SSE 事件类型

---

## 12. Explicitly Not Done Yet

以下功能在 Phase 14 中**仍未完成**：

- [ ] 全局异常中间件
- [ ] 版本化 API surface
- [ ] 前端特定的流式协议变更
- [ ] 更丰富的 async task 生命周期公开元数据
- [ ] 认证/授权或 per-user journal 访问策略

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-13-学习笔记]] — 检索与记忆质量
- [[../phase_14_status.md|phase_14_status.md]] — Phase 14 给 Codex 的状态文档
