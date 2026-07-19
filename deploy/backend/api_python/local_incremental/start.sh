#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)
SHARED_NETWORK="vibedeploy-shared"
DATABASE_CONTAINER="agent-context-router-postgres-1"

docker network inspect "$SHARED_NETWORK" >/dev/null 2>&1 || docker network create "$SHARED_NETWORK"

if ! docker container inspect "$DATABASE_CONTAINER" >/dev/null 2>&1; then
  (cd "$ROOT_DIR" && docker compose up -d postgres)
elif [ "$(docker inspect -f '{{.State.Running}}' "$DATABASE_CONTAINER")" != "true" ]; then
  docker start "$DATABASE_CONTAINER" >/dev/null
fi

if ! docker inspect -f '{{json .NetworkSettings.Networks}}' "$DATABASE_CONTAINER" | grep -q "\"$SHARED_NETWORK\""; then
  docker network connect "$SHARED_NETWORK" "$DATABASE_CONTAINER"
fi

docker compose \
  -p agent-context-router-backend \
  -f "$SCRIPT_DIR/docker-compose.yml" \
  up --build -d

for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 http://127.0.0.1:10061/health >/dev/null 2>&1; then
    echo "[INFO] Agent Context Router backend ready: http://127.0.0.1:10061/health"
    exit 0
  fi
  sleep 1
done

docker logs --tail 100 agent-context-router-backend >&2 || true
exit 1
