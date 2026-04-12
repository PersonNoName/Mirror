from __future__ import annotations

import httpx
import pytest

from app.providers.base import ModelSpec
from app.providers.openai_compat import OpenAICompatibleEmbeddingModel, ProviderRequestError


def _spec(*, base_url: str = "http://127.0.0.1:11434/v1") -> ModelSpec:
    return ModelSpec(
        profile="retrieval.embedding",
        capability="embedding",
        provider_type="openai_compatible",
        vendor="ollama",
        model="qwen3-embedding:4b",
        base_url=base_url,
        api_key_ref=None,
    )


def test_local_provider_client_disables_env_proxy() -> None:
    model = OpenAICompatibleEmbeddingModel(_spec())

    client = model._get_client()

    assert client._trust_env is False


@pytest.mark.asyncio
async def test_provider_request_error_includes_status_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    model = OpenAICompatibleEmbeddingModel(_spec(base_url="https://example.com/v1"))

    async def failing_request(method: str, path: str, json: dict[str, object]) -> httpx.Response:
        request = httpx.Request(method, f"https://example.com{path}")
        return httpx.Response(503, request=request, text="upstream overloaded")

    class StubClient:
        async def request(self, method: str, path: str, json: dict[str, object]) -> httpx.Response:
            return await failing_request(method, path, json)

    monkeypatch.setattr(model, "_get_client", lambda: StubClient())

    with pytest.raises(ProviderRequestError) as excinfo:
        await model.embed(["hello"])

    assert "status=503" in str(excinfo.value)
    assert "upstream overloaded" in str(excinfo.value)
