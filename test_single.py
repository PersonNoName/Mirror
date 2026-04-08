import asyncio
import os
from dotenv import load_dotenv

load_dotenv(override=True)


async def test():
    print("Redis URL:", os.getenv("REDIS_URL"))
    import redis.asyncio as aioredis

    client = aioredis.from_url(os.getenv("REDIS_URL"))
    print("Created client")
    await client.ping()
    print("Ping OK")


try:
    asyncio.run(test())
except Exception as e:
    print("Error:", e)
