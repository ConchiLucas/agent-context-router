#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SHARED_NETWORK="vibedeploy-shared"

docker network inspect "$SHARED_NETWORK" >/dev/null 2>&1 || docker network create "$SHARED_NETWORK"

docker compose \
  -p agent-context-router-web \
  -f "$SCRIPT_DIR/docker-compose.yml" \
  up --build -d

for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:6061/ >/dev/null 2>&1; then
    echo "[INFO] Agent Context Router frontend ready: http://127.0.0.1:6061"
    exit 0
  fi
  sleep 1
done

docker logs --tail 100 agent-context-router-web >&2 || true
exit 1
