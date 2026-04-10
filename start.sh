#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd docker
require_cmd python
require_cmd uvicorn

docker compose up -d

OPENCODE_PORT="${OPENCODE_PORT:-4096}"
APP_PORT="${APP_PORT:-8000}"

OPENCODE_PID=""
cleanup() {
  if [[ -n "$OPENCODE_PID" ]] && kill -0 "$OPENCODE_PID" >/dev/null 2>&1; then
    kill "$OPENCODE_PID" >/dev/null 2>&1 || true
    wait "$OPENCODE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if command -v opencode >/dev/null 2>&1; then
  opencode serve --port "$OPENCODE_PORT" &
  OPENCODE_PID="$!"
else
  echo "Warning: 'opencode' command not found; skipping local OpenCode startup." >&2
fi

uvicorn app.main:app --host 0.0.0.0 --port "$APP_PORT"
