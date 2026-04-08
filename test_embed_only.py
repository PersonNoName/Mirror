import os
from dotenv import load_dotenv

load_dotenv(override=True)

print("EMBEDDING_PROVIDER:", os.getenv("EMBEDDING_PROVIDER"))
print("OLLAMA_BASE_URL:", os.getenv("OLLAMA_BASE_URL"))
print("OLLAMA_EMBED_MODEL:", os.getenv("OLLAMA_EMBED_MODEL"))

from core.vector_retriever import create_embedder
import asyncio


async def test():
    embedder = create_embedder()
    print(f"Embedder Type: {type(embedder).__name__}")
    if type(embedder).__name__ != "EmbedderDummy":
        vec = await embedder.embed("hello")
        print(f"Vector length: {len(vec)}")
    else:
        print("Using Dummy, skipping embed test")


asyncio.run(test())
