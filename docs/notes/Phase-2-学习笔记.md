# Phase 2 学习笔记：Model Provider 实现

> **前置阶段**：[[Phase-1-学习笔记]]  
> **目标**：实现 `ModelProviderRegistry` 和 `openai_compatible` 协议客户端

---

## 目录

- [概述](#概述)
- [1. openai_compatible 客户端](#1-openai_compatible-客户端)
- [2. ModelProviderRegistry](#2-modelproviderregistry)
- [3. 关键设计约束](#3-关键设计约束)
- [4. 验收标准](#4-验收标准)
- [5. 与 Phase 1 接口的对应](#5-与-phase-1-接口的对应)

---

## 概述

### 目标

Phase 2 的目标是**实现 Phase 1 定义的抽象接口**，使全项目的模型调用可以正常工作。

### Phase 2 文件清单

| 文件 | 内容 |
|------|------|
| `app/providers/openai_compat.py` | OpenAI 兼容协议客户端实现 |
| `app/providers/registry.py` | 模型提供者注册表 |

### 四个 profile

| Profile | 用途 | 模型示例 |
|---------|------|---------|
| `reasoning.main` | 主要推理模型 | GPT-4.1 |
| `lite.extraction` | 轻量提取模型 | GPT-4.1-mini |
| `retrieval.embedding` | 嵌入模型 | text-embedding-3-large |
| `retrieval.reranker` | 本地重排序服务 | reranker-v1 |

---

## 1. openai_compatible 客户端

### 1.1 架构

```
业务代码
    ↓
ModelProviderRegistry.get(profile)
    ↓
OpenAICompatibleChatModel / OpenAICompatibleEmbeddingModel / ...
    ↓
httpx.AsyncClient → HTTP 请求 → OpenAI/MiniMax/其他兼容 API
```

### 1.2 ChatModel 实现

#### 普通生成

```python
class OpenAICompatibleChatModel(ChatModel):
    def __init__(self, spec: ModelSpec, timeout: float = 60.0):
        self.spec = spec
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.spec.base_url,
                headers={"Authorization": f"Bearer {self.spec.api_key}"},
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client
    
    async def generate(
        self,
        messages: list[ChatMessage],
        **kwargs
    ) -> ChatResponse:
        client = await self._get_client()
        response = await client.post(
            "/chat/completions",
            json={
                "model": self.spec.model,
                "messages": [m.model_dump() for m in messages],
                **kwargs,
            },
        )
        response.raise_for_status()
        return ChatResponse(**response.json())
    
    async def stream(
        self,
        messages: list[ChatMessage],
        **kwargs
    ) -> AsyncGenerator[ChatDelta, None]:
        client = await self._get_client()
        async with client.stream(
            "POST",
            "/chat/completions",
            json={
                "model": self.spec.model,
                "messages": [m.model_dump() for m in messages],
                "stream": True,
                **kwargs,
            },
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    if line == "data: [DONE]":
                        break
                    yield ChatDelta(**json.loads(line[6:]))
```

### 1.3 EmbeddingModel 实现

#### 批量嵌入（自动分批）

```python
class OpenAICompatibleEmbeddingModel(EmbeddingModel):
    BATCH_SIZE = 100  # OpenAI API 限制
    
    async def embed(
        self,
        texts: list[str],
        **kwargs
    ) -> list[list[float]]:
        results = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i : i + self.BATCH_SIZE]
            batch_results = await self._embed_batch(batch, **kwargs)
            results.extend(batch_results)
        return results
    
    async def _embed_batch(
        self,
        texts: list[str],
        **kwargs
    ) -> list[list[float]]:
        client = await self._get_client()
        response = await client.post(
            "/embeddings",
            json={
                "model": self.spec.model,
                "input": texts,
                **kwargs,
            },
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]
```

### 1.4 RerankerModel 实现

```python
class OpenAICompatibleRerankerModel(RerankerModel):
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 10,
        **kwargs
    ) -> list[RerankResult]:
        client = await self._get_client()
        response = await client.post(
            "/rerank",
            json={
                "model": self.spec.model,
                "query": query,
                "documents": documents,
                "top_k": top_k,
                **kwargs,
            },
        )
        response.raise_for_status()
        return [RerankResult(**r) for r in response.json()["results"]]
```

### 1.5 关键特性

| 特性 | 实现方式 |
|------|---------|
| **无厂商 SDK** | 只用 `httpx.AsyncClient` |
| **超时配置** | `httpx.Timeout` 支持连接超时和读取超时 |
| **指数退避重试** | 使用 `backoff` 或自定义重试逻辑 |
| **流式 SSE** | `httpx-sse` 处理 SSE 流 |
| **连接复用** | 懒加载 `httpx.AsyncClient` 单例 |

---

## 2. ModelProviderRegistry

### 2.1 核心逻辑

```python
class ModelProviderRegistry:
    def __init__(self, routing: dict[str, ModelSpec]):
        self._routing = routing
        self._instances: dict[str, ChatModel | EmbeddingModel | RerankerModel] = {}
        self._lock = asyncio.Lock()
    
    async def chat(self, profile: str) -> ChatModel:
        return await self._get_instance(profile, "chat")
    
    async def embedding(self, profile: str) -> EmbeddingModel:
        return await self._get_instance(profile, "embedding")
    
    async def reranker(self, profile: str) -> RerankerModel:
        return await self._get_instance(profile, "reranker")
    
    async def _get_instance(
        self,
        profile: str,
        capability: str
    ) -> ChatModel | EmbeddingModel | RerankerModel:
        key = f"{profile}:{capability}"
        if key not in self._instances:
            async with self._lock:
                if key not in self._instances:  # 双重检查锁定
                    spec = self._routing[profile]
                    instance = self._create_instance(spec, capability)
                    self._instances[key] = instance
        return self._instances[key]
    
    def _create_instance(
        self,
        spec: ModelSpec,
        capability: str
    ) -> ChatModel | EmbeddingModel | RerankerModel:
        if capability == "chat":
            return OpenAICompatibleChatModel(spec)
        elif capability == "embedding":
            return OpenAICompatibleEmbeddingModel(spec)
        elif capability == "reranker":
            return OpenAICompatibleRerankerModel(spec)
        else:
            raise ValueError(f"Unknown capability: {capability}")
```

### 2.2 工厂函数

```python
def build_routing_from_settings(settings: Settings) -> dict[str, ModelSpec]:
    return {
        "reasoning.main": ModelSpec(
            profile="reasoning.main",
            capability="chat",
            provider_type=settings.model_routing.reasoning_main.provider_type,
            vendor=settings.model_routing.reasoning_main.vendor,
            model=settings.model_routing.reasoning_main.model,
            base_url=settings.model_routing.reasoning_main.base_url,
            api_key=settings.model_routing.reasoning_main.api_key,
        ),
        "lite.extraction": ModelSpec(
            profile="lite.extraction",
            capability="chat",
            ...
        ),
        "retrieval.embedding": ModelSpec(
            profile="retrieval.embedding",
            capability="embedding",
            ...
        ),
        "retrieval.reranker": ModelSpec(
            profile="retrieval.reranker",
            capability="reranker",
            ...
        ),
    }
```

### 2.3 使用示例

```python
from app.config import settings
from app.providers.registry import ModelProviderRegistry, build_routing_from_settings

# 初始化
routing = build_routing_from_settings(settings)
registry = ModelProviderRegistry(routing)

# 获取 ChatModel
chat_model = await registry.chat("reasoning.main")
response = await chat_model.generate(messages)

# 获取 EmbeddingModel
embedding_model = await registry.embedding("retrieval.embedding")
vectors = await embedding_model.embed(["hello world"])
```

---

## 3. 关键设计约束

### 3.1 provider_type vs vendor

| 概念 | 含义 | 示例 |
|------|------|------|
| `provider_type` | 协议族/通信方式 | `openai_compatible`、`ollama`、`native` |
| `vendor` | 实际服务供应商 | `openai`、`minimax`、`local` |

### 3.2 分离的好处

```
配置 1:
provider_type = "openai_compatible"
vendor = "openai"
base_url = "https://api.openai.com/v1"
model = "gpt-4.1"

配置 2:
provider_type = "openai_compatible"
vendor = "minimax"
base_url = "https://api.minimax.chat/v1"
model = "gpt-4.1"
```

**好处**：切换供应商只改配置，不改代码。

### 3.3 不引入厂商 SDK

```python
# 错误示范
from openai import OpenAI  # 引入厂商 SDK

# 正确做法
import httpx
# 所有请求通过 httpx.AsyncClient 发送
```

**原因**：
- 避免厂商 SDK 的版本依赖冲突
- 统一错误处理和重试逻辑
- 保持代码一致性

---

## 4. 验收标准

### 4.1 验收命令

```bash
python -c "
from app.config import settings
from app.providers.registry import ModelProviderRegistry, build_routing_from_settings

r = ModelProviderRegistry(build_routing_from_settings(settings))
print(type(r.chat('reasoning.main')))
print(type(r.embedding('retrieval.embedding')))
print('Phase 2 OK')
"
```

### 4.2 验收检查项

- [ ] `ModelProviderRegistry` 可以通过 profile 获取对应模型实例
- [ ] `OpenAICompatibleChatModel` 支持 `generate()` 和 `stream()`
- [ ] `OpenAICompatibleEmbeddingModel` 支持批量嵌入
- [ ] 所有模型使用 `httpx.AsyncClient`，无厂商 SDK
- [ ] 支持超时配置
- [ ] 懒加载且线程安全

### 4.3 进一步验证（如有 API Key）

```python
# 验证 generate()
chat = await registry.chat("reasoning.main")
resp = await chat.generate([ChatMessage(role="user", content="Hello")])
assert resp.content is not None

# 验证 embed()
emb = await registry.embedding("retrieval.embedding")
vecs = await emb.embed(["Hello world"])
assert len(vecs) == 1 and len(vecs[0]) > 0
```

---

## 5. 与 Phase 1 接口的对应

### 5.1 Phase 1 定义的接口

```python
# app/providers/base.py
class ChatModel(ABC):
    @abstractmethod
    async def generate(self, messages: list[ChatMessage], **kwargs) -> ChatResponse: ...
    
    @abstractmethod
    async def stream(self, messages: list[ChatMessage], **kwargs) -> AsyncGenerator[ChatDelta, None]: ...

class EmbeddingModel(ABC):
    @abstractmethod
    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]: ...

class RerankerModel(ABC):
    @abstractmethod
    async def rerank(self, query: str, documents: list[str], top_k: int = 10, **kwargs) -> list[RerankResult]: ...
```

### 5.2 Phase 2 的实现

| Phase 1 接口 | Phase 2 实现 |
|--------------|-------------|
| `ChatModel.generate()` | `OpenAICompatibleChatModel.generate()` |
| `ChatModel.stream()` | `OpenAICompatibleChatModel.stream()` |
| `EmbeddingModel.embed()` | `OpenAICompatibleEmbeddingModel.embed()` |
| `RerankerModel.rerank()` | `OpenAICompatibleRerankerModel.rerank()` |

---

## 附：相关文档

- [[../PLAN.md|PLAN.md]] — 项目执行计划
- [[Phase-0-学习笔记]] — Phase 0 学习笔记
- [[Phase-1-学习笔记]] — Phase 1 学习笔记
- [[Phase-3-学习笔记|Phase 3]] — 记忆系统（待完成）
