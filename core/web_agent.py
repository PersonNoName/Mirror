import asyncio
from datetime import datetime
from typing import Optional, TYPE_CHECKING, Any

import httpx

from domain.task import Task, TaskResult
from interfaces.agents import SubAgent

if TYPE_CHECKING:
    from interfaces.storage import TaskStoreInterface


SEARCH_RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "urls": {"type": "array", "items": {"type": "string"}},
        "success": {"type": "boolean"},
        "error_type": {"type": "string", "enum": ["RETRYABLE", "FATAL", "NONE"]},
        "error_msg": {"type": "string"},
    },
    "required": ["summary", "success", "error_type"],
}


class WebAgent(SubAgent):
    """
    WebAgent：内置搜索工具闭环的 Sub-agent。
    使用外部搜索 API (Tavily/SerpAPI/Firecrawl) 执行搜索任务。
    """

    name = "web_agent"
    domain = "search"

    def __init__(
        self,
        task_store: "TaskStoreInterface",
        blackboard: Any,
        search_api_key: Optional[str] = None,
        search_provider: str = "tavily",
    ):
        self.task_store = task_store
        self.blackboard = blackboard
        self.search_api_key = search_api_key or ""
        self.search_provider = search_provider

    async def execute(self, task: Task) -> TaskResult:
        try:
            result = await self._perform_search(task)
            await self.blackboard.on_task_complete(task)
            return TaskResult(
                task_id=task.id,
                status="done",
                result=result,
                summary=result.get("summary", ""),
            )
        except httpx.HTTPError as e:
            error_msg = f"HTTP Error: {e}"
            await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
            return TaskResult(
                task_id=task.id,
                status="failed",
                error_trace=f"RETRYABLE: {error_msg}",
            )
        except Exception as e:
            error_msg = f"Unexpected error: {e}"
            await self.blackboard.on_task_failed(task, f"RETRYABLE: {error_msg}")
            return TaskResult(
                task_id=task.id,
                status="failed",
                error_trace=f"RETRYABLE: {error_msg}",
            )

    async def estimate_capability(self, task: Task) -> float:
        text = task.intent.lower()
        keywords = ["搜索", "查询", "网络", "最新", "新闻", "search", "查找", "网址"]
        score = sum(0.2 for kw in keywords if kw in text)
        return min(1.0, score)

    async def cancel(self) -> None:
        print(f"[WebAgent] cancel called for {self.name}")

    async def emit_heartbeat(self, task: Task) -> None:
        task.last_heartbeat_at = datetime.utcnow()
        await self.task_store.update_heartbeat(task.id, task.last_heartbeat_at)

    async def resume(self, task: Task, hitl_result: dict) -> TaskResult:
        print(f"[WebAgent] resume called for task {task.id}")
        return await self.execute(task)

    async def _perform_search(self, task: Task) -> dict:
        query = task.intent
        timeout = task.timeout_seconds or 30

        if self.search_provider == "tavily":
            return await self._search_tavily(query, timeout)
        elif self.search_provider == "serp":
            return await self._search_serp(query, timeout)
        elif self.search_provider == "firecrawl":
            return await self._search_firecrawl(query, timeout)
        else:
            return await self._search_dummy(query)

    async def _search_tavily(self, query: str, timeout: int) -> dict:
        if not self.search_api_key:
            return await self._search_dummy(query)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.search_api_key,
                    "query": query,
                    "max_results": 5,
                    "include_answer": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            urls = [r.get("url", "") for r in data.get("results", [])]
            answer = data.get("answer", "")

            return {
                "summary": answer
                or "\n".join(
                    [r.get("content", "")[:200] for r in data.get("results", [])[:3]]
                ),
                "urls": urls,
                "raw_results": data.get("results", []),
            }

    async def _search_serp(self, query: str, timeout: int) -> dict:
        if not self.search_api_key:
            return await self._search_dummy(query)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={
                    "q": query,
                    "api_key": self.search_api_key,
                    "num": 5,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("organic_results", [])
            urls = [r.get("link", "") for r in results]
            snippets = [r.get("snippet", "") for r in results[:3]]

            return {
                "summary": "\n".join(snippets),
                "urls": urls,
                "raw_results": results,
            }

    async def _search_firecrawl(self, query: str, timeout: int) -> dict:
        if not self.search_api_key:
            return await self._search_dummy(query)

        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://api.firecrawl.dev/v0/search",
                json={
                    "apiKey": self.search_api_key,
                    "query": query,
                    "pageOptions": {"onlyMainContent": True},
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("data", [])
            urls = [r.get("url", "") for r in results]
            summaries = [r.get("description", "") for r in results[:3]]

            return {
                "summary": "\n".join(s for s in summaries if s),
                "urls": urls,
                "raw_results": results,
            }

    async def _search_dummy(self, query: str) -> dict:
        await asyncio.sleep(0.1)
        return {
            "summary": f"[模拟搜索] 查询: {query}",
            "urls": ["https://example.com/1", "https://example.com/2"],
            "raw_results": [],
        }
