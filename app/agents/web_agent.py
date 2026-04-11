"""Minimal real web lookup agent."""

from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

from app.agents.base import SubAgent
from app.tasks.models import Task, TaskResult


class WebAgent(SubAgent):
    """Minimal web lookup agent with bounded search and page fetch behavior."""

    name = "web_agent"
    domain = "search"

    SEARCH_URL = "https://html.duckduckgo.com/html/"
    USER_AGENT = "MirrorWebAgent/1.0"
    MAX_RESULTS = 3
    PAGE_TEXT_LIMIT = 400
    SEARCH_TIMEOUT = 10.0

    def __init__(
        self,
        task_store: Any,
        *,
        search_url: str | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.task_store = task_store
        self.search_url = search_url or self.SEARCH_URL
        self.client_factory = client_factory or httpx.AsyncClient

    async def estimate_capability(self, task: Task) -> float:
        text = f"{task.intent}\n{task.prompt_snapshot}".lower()
        score = 0.0
        keywords = [
            "search",
            "find",
            "lookup",
            "docs",
            "documentation",
            "website",
            "web",
            "retrieve",
            "page",
            "pages",
            "source",
            "sources",
            "搜索",
            "查找",
            "资料",
            "文档",
            "说明",
            "网页",
            "网站",
            "检索",
            "来源",
        ]
        negatives = [
            "code",
            "script",
            "implement",
            "implementation",
            "refactor",
            "debug",
            "browser automation",
            "代码",
            "脚本",
            "实现",
            "重构",
            "调试",
            "浏览器自动化",
        ]
        for keyword in keywords:
            if keyword in text:
                score += 0.16
        for keyword in negatives:
            if keyword in text:
                score -= 0.14
        return max(0.0, min(0.55, score))

    async def execute(self, task: Task) -> TaskResult:
        query = self._build_query(task)
        headers = {"User-Agent": self.USER_AGENT}
        timeout = httpx.Timeout(self.SEARCH_TIMEOUT)

        try:
            async with self.client_factory(headers=headers, timeout=timeout, follow_redirects=True) as client:
                search_response = await client.get(f"{self.search_url}?q={quote_plus(query)}")
                search_response.raise_for_status()
                candidates = self._parse_search_results(search_response.text)
                if not candidates:
                    return TaskResult(
                        task_id=task.id,
                        status="done",
                        output={
                            "summary": f'No usable web results were found for query "{query}".',
                            "query": query,
                            "sources": [],
                            "snippets": [],
                        },
                        metadata={"error_type": "NONE"},
                    )

                sources: list[dict[str, str]] = []
                snippets: list[str] = []
                for candidate in candidates[: self.MAX_RESULTS]:
                    page_text = await self._fetch_page_text(client, candidate["url"])
                    if not page_text:
                        continue
                    sources.append({"title": candidate["title"], "url": candidate["url"]})
                    snippets.append(page_text[: self.PAGE_TEXT_LIMIT])

                if not sources:
                    return TaskResult(
                        task_id=task.id,
                        status="done",
                        output={
                            "summary": (
                                f'Web search succeeded for "{query}", but no result pages could be fetched '
                                "or parsed into usable text."
                            ),
                            "query": query,
                            "sources": [],
                            "snippets": [],
                        },
                        metadata={"error_type": "NONE"},
                    )

                return TaskResult(
                    task_id=task.id,
                    status="done",
                    output={
                        "summary": self._build_summary(query, sources, snippets),
                        "query": query,
                        "sources": sources,
                        "snippets": snippets,
                    },
                    metadata={"error_type": "NONE"},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            return self._failed_result(task, f"Web lookup transient failure: {exc}", "RETRYABLE")
        except httpx.HTTPStatusError as exc:
            error_type = "RETRYABLE" if exc.response.status_code >= 500 else "FATAL"
            return self._failed_result(
                task,
                f"Web lookup HTTP failure: status={exc.response.status_code}",
                error_type,
            )
        except Exception as exc:
            return self._failed_result(task, f"Web lookup failed: {exc}", "FATAL")

    def _build_query(self, task: Task) -> str:
        query = " ".join(part.strip() for part in [task.intent, task.prompt_snapshot] if part.strip())
        return query[:200] or "web lookup"

    async def _fetch_page_text(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            response = await client.get(url)
            response.raise_for_status()
        except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError):
            return ""
        return self._extract_text(response.text)

    @classmethod
    def _parse_search_results(cls, html: str) -> list[dict[str, str]]:
        matches = re.findall(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            re.I | re.S,
        )
        results: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_url, raw_title in matches:
            url = cls._normalize_result_url(raw_url)
            title = cls._clean_fragment(raw_title)
            if not url or not title or url in seen:
                continue
            seen.add(url)
            results.append({"title": title, "url": url})
        return results

    @staticmethod
    def _normalize_result_url(raw_url: str) -> str:
        raw_url = unescape(raw_url).strip()
        parsed = urlparse(raw_url)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            uddg = parse_qs(parsed.query).get("uddg", [""])[0]
            return unescape(uddg).strip()
        return raw_url

    @classmethod
    def _extract_text(cls, html: str) -> str:
        html = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
        html = re.sub(r"<style.*?</style>", " ", html, flags=re.I | re.S)
        html = re.sub(r"<[^>]+>", " ", html)
        html = unescape(html)
        return re.sub(r"\s+", " ", html).strip()

    @classmethod
    def _clean_fragment(cls, value: str) -> str:
        return cls._extract_text(value)

    @staticmethod
    def _build_summary(query: str, sources: list[dict[str, str]], snippets: list[str]) -> str:
        titles = ", ".join(source["title"] for source in sources[:3])
        lead = snippets[0] if snippets else ""
        return f'Found {len(sources)} web source(s) for "{query}": {titles}. Lead snippet: {lead}'

    @staticmethod
    def _failed_result(task: Task, error: str, error_type: str) -> TaskResult:
        return TaskResult(
            task_id=task.id,
            status="failed",
            error=error,
            metadata={"error_type": error_type},
        )
