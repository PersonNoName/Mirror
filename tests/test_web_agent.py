from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.agents.web_agent import WebAgent
from app.tasks.models import Task


class MockResponse:
    def __init__(self, text: str = "", status_code: int = 200, url: str = "https://example.com") -> None:
        self.text = text
        self.status_code = status_code
        self.url = url
        self.request = httpx.Request("GET", url)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status={self.status_code}",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


class MockAsyncClient:
    def __init__(self, handlers: dict[str, object], **kwargs: object) -> None:
        self.handlers = handlers
        self.kwargs = kwargs
        self.calls: list[str] = []

    async def __aenter__(self) -> MockAsyncClient:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def get(self, url: str) -> MockResponse:
        self.calls.append(url)
        handler = self.handlers.get(url)
        if isinstance(handler, Exception):
            raise handler
        if isinstance(handler, MockResponse):
            return handler
        raise AssertionError(f"unexpected url: {url}")


def make_client_factory(handlers: dict[str, object]):
    def factory(**kwargs: object) -> MockAsyncClient:
        return MockAsyncClient(handlers, **kwargs)

    return factory


def make_task(intent: str, prompt_snapshot: str = "") -> Task:
    return Task(id="task-web", intent=intent, prompt_snapshot=prompt_snapshot)


@pytest.mark.asyncio
async def test_web_agent_estimate_capability_prefers_search_prompts() -> None:
    agent = WebAgent(task_store=object())

    search_score = await agent.estimate_capability(make_task("搜索 FastAPI 文档"))
    code_score = await agent.estimate_capability(make_task("implement python function for httpx"))

    assert search_score > code_score
    assert search_score > 0.0
    assert code_score < 0.2


@pytest.mark.asyncio
async def test_web_agent_execute_returns_real_lookup_output() -> None:
    search_url = "https://search.test/html/"
    agent = WebAgent(
        task_store=object(),
        search_url=search_url,
        client_factory=make_client_factory(
            {
                f"{search_url}?q=latest+fastapi+docs+how+to+use": MockResponse(
                    text=(
                        '<a class="result__a" href="https://docs.example.com/fastapi">FastAPI Docs</a>'
                        '<a class="result__a" href="https://example.com/tutorial">Tutorial</a>'
                    ),
                    url=f"{search_url}?q=latest+fastapi+docs+how+to+use",
                ),
                "https://docs.example.com/fastapi": MockResponse(
                    text=(
                        "<html><body>FastAPI documentation explains routing and dependency injection."
                        "</body></html>"
                    ),
                    url="https://docs.example.com/fastapi",
                ),
                "https://example.com/tutorial": MockResponse(
                    text="<html><body>Tutorial page with usage examples.</body></html>",
                    url="https://example.com/tutorial",
                ),
            }
        ),
    )

    result = await agent.execute(make_task("latest fastapi docs", "how to use"))

    assert result.status == "done"
    assert result.output is not None
    assert result.output["query"] == "latest fastapi docs how to use"
    assert len(result.output["sources"]) == 2
    assert result.output["sources"][0]["title"] == "FastAPI Docs"
    assert "routing and dependency injection" in result.output["snippets"][0]
    assert "FastAPI Docs" in result.output["summary"]
    assert "placeholder" not in result.output["summary"].lower()


@pytest.mark.asyncio
async def test_web_agent_execute_keeps_usable_results_when_one_page_fails() -> None:
    search_url = "https://search.test/html/"
    agent = WebAgent(
        task_store=object(),
        search_url=search_url,
        client_factory=make_client_factory(
            {
                f"{search_url}?q=python+httpx": MockResponse(
                    text=(
                        '<a class="result__a" href="https://docs.example.com/httpx">HTTPX Docs</a>'
                        '<a class="result__a" href="https://bad.example.com">Broken</a>'
                    ),
                    url=f"{search_url}?q=python+httpx",
                ),
                "https://docs.example.com/httpx": MockResponse(
                    text="<html><body>HTTPX supports async clients and timeout controls.</body></html>",
                    url="https://docs.example.com/httpx",
                ),
                "https://bad.example.com": httpx.ConnectError(
                    "failed",
                    request=httpx.Request("GET", "https://bad.example.com"),
                ),
            }
        ),
    )

    result = await agent.execute(make_task("python httpx"))

    assert result.status == "done"
    assert result.output is not None
    assert len(result.output["sources"]) == 1
    assert result.output["sources"][0]["title"] == "HTTPX Docs"
    assert "HTTPX supports async clients" in result.output["snippets"][0]


@pytest.mark.asyncio
async def test_web_agent_execute_returns_failed_on_total_search_failure() -> None:
    search_url = "https://search.test/html/"
    agent = WebAgent(
        task_store=object(),
        search_url=search_url,
        client_factory=make_client_factory(
            {
                f"{search_url}?q=network+failure": httpx.ConnectError(
                    "down",
                    request=httpx.Request("GET", f"{search_url}?q=network+failure"),
                ),
            }
        ),
    )

    result = await agent.execute(make_task("network failure"))

    assert result.status == "failed"
    assert result.metadata["error_type"] == "RETRYABLE"
    assert result.error is not None
    assert "transient failure" in result.error


@pytest.mark.asyncio
async def test_web_agent_execute_returns_truthful_done_for_no_results() -> None:
    search_url = "https://search.test/html/"
    agent = WebAgent(
        task_store=object(),
        search_url=search_url,
        client_factory=make_client_factory(
            {
                f"{search_url}?q=no+results": MockResponse(
                    text="<html><body>nothing useful</body></html>",
                    url=f"{search_url}?q=no+results",
                ),
            }
        ),
    )

    result = await agent.execute(make_task("no results"))

    assert result.status == "done"
    assert result.output is not None
    assert result.output["sources"] == []
    assert result.output["snippets"] == []
    assert "No usable web results were found" in result.output["summary"]


@pytest.mark.asyncio
async def test_web_agent_execute_returns_fatal_for_non_retryable_http_failure() -> None:
    search_url = "https://search.test/html/"
    agent = WebAgent(
        task_store=object(),
        search_url=search_url,
        client_factory=make_client_factory(
            {
                f"{search_url}?q=bad+request": MockResponse(
                    text="bad request",
                    status_code=400,
                    url=f"{search_url}?q=bad+request",
                ),
            }
        ),
    )

    result = await agent.execute(make_task("bad request"))

    assert result.status == "failed"
    assert result.metadata["error_type"] == "FATAL"
    assert result.error == "Web lookup HTTP failure: status=400"
