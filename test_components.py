import asyncio
import os
from dotenv import load_dotenv

load_dotenv(override=True)


async def test_llm():
    print("[1] Testing LLM...")
    from services.llm import create_llm

    llm = create_llm()
    print(f"    LLM Type: {type(llm).__name__}")
    try:
        result = await llm.generate("Say 'hello'")
        print(f"    Result: {result[:100] if result else 'EMPTY'}")
        print("    [PASS]")
    except Exception as e:
        print(f"    [FAIL] {e}")


async def test_embedder():
    print("\n[2] Testing Embedder...")
    from core.vector_retriever import create_embedder

    embedder = create_embedder()
    print(f"    Type: {type(embedder).__name__}")
    try:
        vec = await embedder.embed("hello")
        print(f"    Vector length: {len(vec)}")
        print("    [PASS]")
    except Exception as e:
        print(f"    [FAIL] {e}")


async def test_redis():
    print("\n[3] Testing Redis...")
    import redis.asyncio as aioredis

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        print("    [SKIP] REDIS_URL not set")
        return
    try:
        client = aioredis.from_url(redis_url)
        await client.ping()
        await client.close()
        print("    [PASS]")
    except Exception as e:
        print(f"    [FAIL] {e}")


async def test_postgres():
    print("\n[4] Testing PostgreSQL...")
    import asyncpg

    pg_url = os.getenv("POSTGRES_URL", "").strip()
    if not pg_url:
        print("    [SKIP] POSTGRES_URL not set")
        return
    try:
        pool = await asyncpg.create_pool(pg_url, min_size=1, max_size=1)
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
        await pool.close()
        print(f"    [PASS] result={result}")
    except Exception as e:
        print(f"    [FAIL] {e}")


async def test_eventbus():
    print("\n[5] Testing EventBus...")
    from events.event_bus import EventBus, EVENT_BUS_CONFIG

    try:
        eb = EventBus(EVENT_BUS_CONFIG)
        await eb.start()
        await eb.stop()
        print("    [PASS]")
    except Exception as e:
        print(f"    [FAIL] {e}")


async def main():
    await test_llm()
    await test_embedder()
    await test_redis()
    await test_postgres()
    await test_eventbus()
    print("\nDone")


asyncio.run(main())
