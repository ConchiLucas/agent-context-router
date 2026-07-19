#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)

echo "[STEP] stop Next.js frontend"
sh "$ROOT_DIR/deploy/frontend/web_next/local_full/stop.sh"

echo "[STEP] stop FastAPI backend"
sh "$ROOT_DIR/deploy/backend/api_python/local_incremental/stop.sh"

echo "[INFO] agent-context-router application services stopped"
