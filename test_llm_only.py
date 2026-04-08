import asyncio
import os
from dotenv import load_dotenv

load_dotenv(override=True)


async def test():
    print("Testing LLM...")
    from services.llm import create_llm

    llm = create_llm()
    print(f"LLM Type: {type(llm).__name__}")
    result = await llm.generate("hi")
    print(f"Result: {result[:50] if result else 'EMPTY'}")


asyncio.run(test())
