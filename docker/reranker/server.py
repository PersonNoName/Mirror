from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForSequenceClassification, AutoTokenizer


DEFAULT_MODEL_ID = os.getenv("RERANKER_MODEL_ID", "BAAI/bge-reranker-v2-m3")
DEFAULT_DEVICE = os.getenv("RERANKER_DEVICE", "cpu")
MAX_BATCH_SIZE = int(os.getenv("RERANKER_BATCH_SIZE", "16"))
LOCAL_MODEL_ROOT = os.getenv("RERANKER_LOCAL_MODEL_ROOT", "/models/local-reranker")
MODEL_ALIASES = {
    "reranker-v1": DEFAULT_MODEL_ID,
    DEFAULT_MODEL_ID: DEFAULT_MODEL_ID,
}
LOADED_MODELS: set[str] = set()

app = FastAPI(title="Mirror Reranker", version="1.0.0")


class RerankRequest(BaseModel):
    model: str = Field(default=DEFAULT_MODEL_ID)
    query: str
    documents: list[str]
    top_n: int | None = None
    return_documents: bool = True


class HealthResponse(BaseModel):
    status: str
    model: str
    device: str
    model_loaded: bool


class ReadinessResponse(BaseModel):
    status: str
    model: str
    device: str
    model_loaded: bool


def _resolve_device() -> str:
    if DEFAULT_DEVICE != "auto":
        return DEFAULT_DEVICE
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _resolve_model_id(requested_model: str) -> str:
    normalized = (requested_model or "").strip()
    if not normalized:
        return DEFAULT_MODEL_ID
    return MODEL_ALIASES.get(normalized, normalized)


def _is_model_loaded(model_id: str) -> bool:
    resolved = _resolve_model_id(model_id)
    return resolved in LOADED_MODELS


def _resolve_local_model_path(model_id: str) -> str | None:
    model_root = Path(LOCAL_MODEL_ROOT)
    if not model_root.exists():
        return None
    snapshots_dir = model_root / "snapshots"
    if snapshots_dir.exists():
        snapshots = sorted(path for path in snapshots_dir.iterdir() if path.is_dir())
        if snapshots:
            return str(snapshots[-1])
    config_file = model_root / "config.json"
    if config_file.exists():
        return str(model_root)
    return None


@lru_cache(maxsize=2)
def _load_model(model_id: str) -> tuple[Any, Any, str]:
    resolved_model_id = _resolve_model_id(model_id)
    local_model_path = _resolve_local_model_path(resolved_model_id)
    load_target = local_model_path or resolved_model_id
    tokenizer = AutoTokenizer.from_pretrained(
        load_target,
        local_files_only=bool(local_model_path),
    )
    model = AutoModelForSequenceClassification.from_pretrained(
        load_target,
        local_files_only=bool(local_model_path),
    )
    device = _resolve_device()
    model.to(device)
    model.eval()
    LOADED_MODELS.add(resolved_model_id)
    return tokenizer, model, device


def _score_documents(query: str, documents: list[str], *, model_id: str) -> list[dict[str, Any]]:
    tokenizer, model, device = _load_model(_resolve_model_id(model_id))
    pairs = [[query, document] for document in documents]
    scores: list[float] = []
    with torch.inference_mode():
        for start in range(0, len(pairs), MAX_BATCH_SIZE):
            batch_pairs = pairs[start : start + MAX_BATCH_SIZE]
            encoded = tokenizer(
                batch_pairs,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits
            if logits.ndim == 2 and logits.shape[1] > 1:
                batch_scores = logits[:, 0]
            else:
                batch_scores = logits.reshape(-1)
            scores.extend(float(item) for item in batch_scores.detach().cpu().tolist())

    ranked = [
        {
            "index": index,
            "document": document,
            "relevance_score": score,
        }
        for index, (document, score) in enumerate(zip(documents, scores, strict=False))
    ]
    ranked.sort(key=lambda item: item["relevance_score"], reverse=True)
    return ranked


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        model=DEFAULT_MODEL_ID,
        device=_resolve_device(),
        model_loaded=_is_model_loaded(DEFAULT_MODEL_ID),
    )


@app.get("/ready", response_model=ReadinessResponse)
async def ready() -> ReadinessResponse:
    model_loaded = _is_model_loaded(DEFAULT_MODEL_ID)
    return ReadinessResponse(
        status="ok" if model_loaded else "starting",
        model=DEFAULT_MODEL_ID,
        device=_resolve_device(),
        model_loaded=model_loaded,
    )


@app.post("/rerank")
async def rerank(request: RerankRequest) -> dict[str, Any]:
    query = request.query.strip()
    documents = [item for item in request.documents if isinstance(item, str) and item.strip()]
    if not query:
        raise HTTPException(status_code=400, detail="query must not be empty")
    if not documents:
        return {"results": []}

    ranked = _score_documents(query, documents, model_id=request.model or DEFAULT_MODEL_ID)
    if request.top_n is not None and request.top_n > 0:
        ranked = ranked[: request.top_n]
    if not request.return_documents:
        ranked = [
            {"index": item["index"], "relevance_score": item["relevance_score"]}
            for item in ranked
        ]
    return {"results": ranked}
