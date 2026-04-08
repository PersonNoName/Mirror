import asyncio
import aiohttp


async def test():
    url = "http://localhost:11434/api/embed"
    data = {"model": "qwen3-embedding:4b", "input": ["hello"]}

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=data) as response:
                print("Status:", response.status)
                text = await response.text()
                print("Response:", text[:500])
        except Exception as e:
            print("Error:", e)


asyncio.run(test())
