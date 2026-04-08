import json
import os

from openai import AsyncOpenAI


class LLMInterface:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        base_url: str | None = None,
    ):
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def generate(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        if content is None:
            print("[LLMInterface] Received null content")
            return ""
        return content

    async def generate_json(self, prompt: str) -> dict:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "user", "content": "请以JSON格式返回。"},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            print("[LLMInterface] Received null content")
            return {}
        return json.loads(content)


class MiniMaxLLM:
    def __init__(
        self,
        api_key: str,
        model: str = "MiniMax-Text-01",
        base_url: str = "https://api.minimax.chat/v1",
    ):
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    async def generate(self, prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            if not response.choices or not response.choices[0].message:
                print(f"[MiniMaxLLM] Invalid response structure: {response}")
                return ""
            content = response.choices[0].message.content
            if content is None:
                print("[MiniMaxLLM] Received null content")
                return ""
            return content
        except Exception as e:
            print(f"[MiniMaxLLM] Error parsing response: {e}, response: {response}")
            return ""

    async def generate_json(self, prompt: str) -> dict:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "user", "content": prompt},
                {"role": "user", "content": "请以JSON格式返回。"},
            ],
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            print("[MiniMaxLLM] Received null content")
            return {}
        return json.loads(content)


class LLMDummy:
    async def generate(self, prompt: str) -> str:
        return f"[LLM Mock Response to: {prompt[:50]}...]"

    async def generate_json(self, prompt: str) -> dict:
        return {"confidence": 0.6, "root_cause": "mock", "lesson": "mock"}


def create_llm():
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    if not api_key:
        print("[LLMFactory] No API key found, using Dummy")
        return LLMDummy()

    if LLM_PROVIDER == "minimax":
        base_url = os.getenv("LLM_BASE_URL", "https://api.minimax.chat/v1").strip()
        model = os.getenv("LLM_MODEL", "MiniMax-Text-01").strip()
        print(f"[LLMFactory] Using MiniMax: {base_url}, model={model}")
        return MiniMaxLLM(api_key=api_key, base_url=base_url, model=model)

    if LLM_PROVIDER == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
        model = os.getenv("OLLAMA_LLM_MODEL", "llama3").strip()
        print(f"[LLMFactory] Using Ollama: {base_url}, model={model}")
        return LLMInterface(api_key=api_key, base_url=base_url, model=model)

    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    model = os.getenv("LLM_MODEL", "gpt-4").strip()
    print(f"[LLMFactory] Using OpenAI-compatible: base_url={base_url}, model={model}")
    return LLMInterface(api_key=api_key, base_url=base_url, model=model)
