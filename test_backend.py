import asyncio
import os
from dotenv import load_dotenv

load_dotenv(override=True)


async def test():
    print("=" * 50)

    # Test Redis
    print("\n[1] Redis Test...")
    import redis.asyncio as aioredis

    try:
        client = aioredis.from_url(os.getenv("REDIS_URL"))
        await client.ping()
        await client.close()
        print("    [PASS] Redis connected")
    except Exception as e:
        print(f"    [FAIL] {e}")

    # Test PostgreSQL
    print("\n[2] PostgreSQL Test...")
    import asyncpg

    try:
        pool = await asyncpg.create_pool(
            os.getenv("POSTGRES_URL"), min_size=1, max_size=1
        )
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
        await pool.close()
        print(f"    [PASS] PostgreSQL connected, query result: {result}")
    except Exception as e:
        print(f"    [FAIL] {e}")

    # Test Neo4j
    print("\n[3] Neo4j Test...")
    from services.graph_db import Neo4jGraphDB

    try:
        graph = Neo4jGraphDB(
            uri=os.getenv("NEO4J_URI"),
            user=os.getenv("NEO4J_USER"),
            password=os.getenv("NEO4J_PASSWORD"),
        )
        print("    [PASS] Neo4j driver initialized")
        await graph.close()
    except Exception as e:
        print(f"    [FAIL] {e}")

    # Test EventBus
    print("\n[4] EventBus Test...")
    from events.event_bus import EventBus, EVENT_BUS_CONFIG

    try:
        eb = EventBus(EVENT_BUS_CONFIG)
        await eb.start()
        await eb.stop()
        print("    [PASS] EventBus works")
    except Exception as e:
        print(f"    [FAIL] {e}")

    print("\n" + "=" * 50)
    print("Basic tests complete")


asyncio.run(test())
