#!/usr/bin/env bash
# Start Redis (if not running), API, and worker for local Phase 0 development.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  echo "Setup first: python3 -m venv .venv && source .venv/bin/activate && pip install -e '.[platform,dev]'"
  exit 1
fi
source .venv/bin/activate

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export DATABASE_URL="${DATABASE_URL:-sqlite:///./data/paper_extract.db}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379}"
export STORAGE_ROOT="${STORAGE_ROOT:-./data/storage}"

mkdir -p data/storage data

if ! redis-cli -u "$REDIS_URL" ping >/dev/null 2>&1; then
  echo "Redis not reachable at $REDIS_URL"
  echo "Start Redis: docker compose up -d redis   OR   brew services start redis"
  exit 1
fi

echo "Starting API on :8000 and worker..."
trap 'kill 0' EXIT INT TERM

paper-extract-api &
API_PID=$!
paper-extract-worker &
WORKER_PID=$!

echo "API pid=$API_PID  worker pid=$WORKER_PID"
echo "Health: curl http://localhost:8000/api/v1/health"
wait
