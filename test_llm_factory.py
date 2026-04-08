import os
from dotenv import load_dotenv

load_dotenv(override=True)

print("OPENAI_API_KEY:", os.getenv("OPENAI_API_KEY", "").strip()[:20] + "...")
print("LLM_PROVIDER:", os.getenv("LLM_PROVIDER", "").strip())
print("LLM_BASE_URL:", os.getenv("LLM_BASE_URL", "").strip())
print("LLM_MODEL:", os.getenv("LLM_MODEL", "").strip())

from services.llm import create_llm
import asyncio


async def test():
    llm = create_llm()
    print("LLM type:", type(llm).__name__)
    result = await llm.generate("say hi")
    print("Result:", result[:100])


asyncio.run(test())
