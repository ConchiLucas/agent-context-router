#!/usr/bin/env sh

# Start the shared config center containers when they already exist but are down.
# Does not rebuild images or create a new compose project from scratch if Docker
# cannot reuse the current API/Web containers.

set -eu

ROOT="${CONTEXT_ROUTER_SHARED_CONFIG_CENTER_ROOT:-/Users/conchi/workforce/my_github_workforce/ai_share_config}"
COMPOSE_FILE="${ROOT}/docker-compose.yml"
API_CONTAINER="${SHARED_CONFIG_CENTER_API_CONTAINER:-shared-config-center-api}"
WEB_CONTAINER="${SHARED_CONFIG_CENTER_WEB_CONTAINER:-shared-config-center-web}"
SHARED_NETWORK="${SHARED_NETWORK:-vibedeploy-shared}"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "错误：找不到共享配置中心：$COMPOSE_FILE" >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "错误：未找到 docker" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "错误：Docker Desktop 尚未就绪" >&2
  exit 1
fi

container_running() {
  [ "$(docker inspect --format '{{.State.Running}}' "$1" 2>/dev/null || true)" = "true" ]
}

container_exists() {
  docker inspect "$1" >/dev/null 2>&1
}

if container_running "$API_CONTAINER" && container_running "$WEB_CONTAINER"; then
  echo "[PASS] 共享配置中心已在运行"
  exit 0
fi

if ! docker network inspect "$SHARED_NETWORK" >/dev/null 2>&1; then
  docker network create --driver bridge "$SHARED_NETWORK" >/dev/null
fi

if container_exists "$API_CONTAINER" && container_exists "$WEB_CONTAINER"; then
  echo "[STEP] 启动已有共享配置中心容器"
  docker start "$API_CONTAINER" >/dev/null
  docker start "$WEB_CONTAINER" >/dev/null
else
  echo "[STEP] 使用现有镜像拉起共享配置中心"
  if docker compose version >/dev/null 2>&1; then
    docker compose --project-directory "$ROOT" -f "$COMPOSE_FILE" up -d --no-build
  else
    docker-compose --project-directory "$ROOT" -f "$COMPOSE_FILE" up -d --no-build
  fi
fi

if container_running "$API_CONTAINER" && container_running "$WEB_CONTAINER"; then
  echo "[PASS] 共享配置中心已就绪"
  exit 0
fi

echo "错误：共享配置中心未能启动" >&2
exit 1
