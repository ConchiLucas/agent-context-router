#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)

echo "[STEP] start FastAPI backend"
sh "$ROOT_DIR/deploy/backend/api_python/local_full/start.sh"

echo "[STEP] start Next.js frontend"
sh "$ROOT_DIR/deploy/frontend/web_next/local_full/start.sh"

echo "[INFO] agent-context-router full deploy completed"
