"""HTTP-based model providers for OpenAI-compatible APIs."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from urllib.parse import urlparse
from typing import Any

import httpx
from httpx_sse import aconnect_sse

from app.providers.base import ChatModel, EmbeddingModel, ModelSpec, RerankerModel


class ProviderRequestError(RuntimeError):
    """Raised when a provider request fails after retries."""


class _HTTPProviderMixin:
    """Shared HTTP client and retry utilities for provider implementations."""

    def __init__(self, spec: ModelSpec) -> None:
        self.spec = spec
        self._client: httpx.AsyncClient | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.spec.api_key_ref:
            headers["Authorization"] = f"Bearer {self.spec.api_key_ref}"
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.spec.timeout_seconds)

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            parsed = urlparse(self.spec.base_url)
            host = parsed.hostname or ""
            self._client = httpx.AsyncClient(
                base_url=self.spec.base_url.rstrip("/"),
                headers=self._headers(),
                timeout=self._timeout(),
                trust_env=host not in {"127.0.0.1", "localhost", "::1"},
            )
        return self._client

    @staticmethod
    def _is_retryable_status(status_code: int) -> bool:
        return status_code == 429 or 500 <= status_code < 600

    @staticmethod
    def _format_error_detail(error: Exception | None) -> str:
        if error is None:
            return ""
        response = getattr(error, "response", None)
        if response is not None:
            status_code = getattr(response, "status_code", None)
            try:
                body = response.text
            except Exception:
                body = ""
            body_preview = body[:200].replace("\n", " ").strip()
            if status_code is not None and body_preview:
                return f" (status={status_code}, body={body_preview})"
            if status_code is not None:
                return f" (status={status_code})"
        return f" ({error.__class__.__name__})"

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any],
    ) -> Any:
        last_error: Exception | None = None
        attempts = max(1, self.spec.max_retries + 1)
        client = self._get_client()

        for attempt in range(1, attempts + 1):
            try:
                response = await client.request(method, path, json=json_body)
                if self._is_retryable_status(response.status_code):
                    raise httpx.HTTPStatusError(
                        "retryable provider response",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                response = getattr(exc, "response", None)
                should_retry = isinstance(
                    exc,
                    (httpx.TimeoutException, httpx.NetworkError),
                ) or (
                    response is not None and self._is_retryable_status(response.status_code)
                )
                if not should_retry or attempt >= attempts:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        detail = self._format_error_detail(last_error)
        raise ProviderRequestError(
            f"provider request failed for {self.spec.profile}{detail}"
        ) from last_error


class OpenAICompatibleChatModel(_HTTPProviderMixin, ChatModel):
    """Chat provider using the OpenAI-compatible chat completions API."""

    async def generate(self, messages: list[dict[str, Any]], **kwargs: Any) -> Any:
        payload = {"model": self.spec.model, "messages": messages, **kwargs}
        return await self._request_json("POST", "/chat/completions", json_body=payload)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        payload = {"model": self.spec.model, "messages": messages, "stream": True, **kwargs}
        attempts = max(1, self.spec.max_retries + 1)
        last_error: Exception | None = None
        client = self._get_client()

        for attempt in range(1, attempts + 1):
            try:
                async with aconnect_sse(
                    client,
                    "POST",
                    "/chat/completions",
                    json=payload,
                ) as event_source:
                    async for sse in event_source.aiter_sse():
                        if not sse.data or sse.data == "[DONE]":
                            continue
                        try:
                            yield json.loads(sse.data)
                        except json.JSONDecodeError:
                            continue
                    return
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                response = getattr(exc, "response", None)
                should_retry = isinstance(
                    exc,
                    (httpx.TimeoutException, httpx.NetworkError),
                ) or (
                    response is not None and self._is_retryable_status(response.status_code)
                )
                if not should_retry or attempt >= attempts:
                    break
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        detail = self._format_error_detail(last_error)
        raise ProviderRequestError(
            f"provider stream failed for {self.spec.profile}{detail}"
        ) from last_error


class OpenAICompatibleEmbeddingModel(_HTTPProviderMixin, EmbeddingModel):
    """Embedding provider using the OpenAI-compatible embeddings API."""

    def __init__(self, spec: ModelSpec, batch_size: int = 32) -> None:
        super().__init__(spec)
        self.batch_size = batch_size

    async def embed(self, texts: list[str], **kwargs: Any) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            payload = {"model": self.spec.model, "input": batch, **kwargs}
            data = await self._request_json("POST", "/embeddings", json_body=payload)
            items = data.get("data", [])
            ordered = sorted(items, key=lambda item: item.get("index", 0))
            vectors.extend(item["embedding"] for item in ordered)
        return vectors


class OpenAICompatibleRerankerModel(_HTTPProviderMixin, RerankerModel):
    """HTTP reranker provider for local or compatible reranker services."""

    async def rerank(
        self,
        query: str,
        docs: list[str],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        payload = {"model": self.spec.model, "query": query, "documents": docs, **kwargs}
        data = await self._request_json("POST", "/rerank", json_body=payload)
        if "results" in data and isinstance(data["results"], list):
            return [dict(item) for item in data["results"]]
        if "data" in data and isinstance(data["data"], list):
            return [dict(item) for item in data["data"]]
        if isinstance(data, list):
            return [dict(item) for item in data]
        raise ProviderRequestError(f"unexpected reranker response for {self.spec.profile}")
