import asyncio
from openai import AsyncOpenAI


async def test():
    client = AsyncOpenAI(
        api_key="sk-cp-xxVuqzsXofWxuLe2GHTu7eLEn_2xCJkOPwW9E8t3N2KvwFsZmEJb5cI1E1FVbHy44ZmE9970nPtXCFFVGUxny_9T3ZznwKxd_8BJ4jM-A7s3ecCG3kKNGts",
        base_url="https://api.minimax.chat/v1",
    )
    try:
        response = await client.chat.completions.create(
            model="MiniMax-M2.7", messages=[{"role": "user", "content": "say hi"}]
        )
        print("Success:", response.choices[0].message.content)
    except Exception as e:
        print("Error:", e)


asyncio.run(test())
