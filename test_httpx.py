import asyncio
import httpx


async def test():
    url = "http://localhost:11434/api/embed"
    data = {"model": "qwen3-embedding:4b", "input": ["hello"]}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, json=data)
            print("Status:", response.status_code)
            print("Headers:", dict(response.headers))
            print("Response:", response.text[:500])
        except Exception as e:
            print("Error:", e)


asyncio.run(test())
