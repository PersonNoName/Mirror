from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.agent_app import AgentApplication, create_production_config

load_dotenv(override=True)


class ChatRequest(BaseModel):
    user_id: str
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str
    action: str
    task_id: Optional[str] = None
    inner_thoughts: Optional[str] = None


_state: AgentApplication | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _state
    config = await create_production_config()
    _state = AgentApplication(config)
    await _state.initialize()
    yield
    if _state:
        await _state.shutdown()


app = FastAPI(title="Mirror Agent API", lifespan=lifespan)


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    if _state is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")

    result = await _state.chat(
        request.user_id,
        request.session_id,
        request.message,
    )

    return ChatResponse(
        reply=result["reply"],
        action=result["action"],
        task_id=result.get("task_id"),
        inner_thoughts=result.get("inner_thoughts"),
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
