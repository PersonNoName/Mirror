# Reranker Service

The repo now includes a standalone local reranker service for the `retrieval.reranker` profile.

## Files

- `docker/reranker/Dockerfile`
- `docker/reranker/server.py`
- `docker-compose.yml`

## Start

```powershell
docker compose up -d reranker
docker compose ps reranker
```

## Endpoints

- `GET /health`
- `GET /ready`
- `POST /rerank`

Example request:

```json
{
  "model": "reranker-v1",
  "query": "python preference",
  "documents": [
    "User likes Python.",
    "User prefers coffee at night."
  ],
  "top_n": 2
}
```

Example response:

```json
{
  "results": [
    {
      "index": 0,
      "document": "User likes Python.",
      "relevance_score": 8.12
    }
  ]
}
```

## Environment Variables

- `RERANKER_PORT`
- `RERANKER_MODEL_ID`
- `RERANKER_DEVICE`
- `RERANKER_BATCH_SIZE`
- `RERANKER_LOCAL_MODEL_ROOT`

Defaults:

- port: `8081`
- model: `BAAI/bge-reranker-v2-m3`
- device: `cpu`

## Notes

- The model cache is stored in the `reranker_model_cache` Docker volume.
- The compose service also bind-mounts the host Hugging Face cache for `BAAI/bge-reranker-v2-m3` into `/models/local-reranker`.
- If `/models/local-reranker/snapshots/...` exists, the service loads from that local snapshot first and avoids network downloads.
- First startup will be slower because the Hugging Face model must be downloaded.
- `/health` is now a lightweight liveness check and does not trigger model loading.
- `/ready` reports whether the default reranker model has already been loaded into the process.
- The app already points `MODEL_RETRIEVAL_RERANKER_BASE_URL` at `http://127.0.0.1:8081`, so no code change is needed after the container is up.
