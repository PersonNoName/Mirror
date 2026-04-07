import json

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
