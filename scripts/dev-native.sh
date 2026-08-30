#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

native_require_command uv
native_require_node22
native_require_command npm
native_require_command python3
native_prepare_runtime

cleanup() {
  for process_id in ${backend_process:-} ${frontend_process:-} ${runner_process:-}; do
    if [[ -n "$process_id" ]]; then
      kill -TERM "$process_id" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

cd "$native_repo_root/backend"
uv run alembic upgrade head
uv run uvicorn context_router.main:create_app --factory --reload --host 127.0.0.1 --port 49173 &
backend_process=$!
native_wait_http "$CONTEXT_ROUTER_CONTROL_URL/health" "Backend"

python3 "$native_repo_root/scripts/context_router_host_runner.py" \
  --control-url "$CONTEXT_ROUTER_CONTROL_URL" \
  --workspace-root "$CONTEXT_ROUTER_WORKSPACE_ROOT" \
  --runtime-root "$native_runtime_root" \
  --token-path "$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH" &
runner_process=$!

cd "$native_repo_root/frontend"
node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 49175 &
frontend_process=$!

print "Native 开发环境已启动，按 Ctrl-C 停止；业务 Workspace 容器不会被停止"
wait "$backend_process"
