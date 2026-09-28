#!/usr/bin/env sh

# Start Personal Utils Hub (frontend :39889, backend :39888) when it is down.
# Delegates to the project's start.sh, which skips ports that are already listening.

set -eu

ROOT="${CONTEXT_ROUTER_PERSONAL_UTILS_ROOT:-/Users/conchi/workforce/my_github_workforce/personal_utils}"
START="$ROOT/start.sh"
BACKEND_PORT=39888
FRONTEND_PORT=39889

is_listening() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

if [ ! -f "$START" ]; then
  echo "错误：找不到 Personal Utils Hub：$START" >&2
  exit 1
fi

if is_listening "$BACKEND_PORT" && is_listening "$FRONTEND_PORT"; then
  echo "[PASS] Personal Utils Hub 已在运行"
  exit 0
fi

echo "[STEP] 启动 Personal Utils Hub"
sh "$START"
