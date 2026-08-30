#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

service_name=${1:?缺少 Native 服务名}
uv_bin=${2:-}
python_bin=${3:-}
node_bin=${4:-}

case "$service_name" in
  backend)
    print "$$" > "$native_backend_pid"
    exec >> "$native_runtime_root/backend.log" 2>&1
    cd "$native_repo_root/backend"
    exec "$uv_bin" run uvicorn context_router.main:create_app --factory --host 127.0.0.1 --port 49173
    ;;
  runner)
    print "$$" > "$native_runner_pid"
    exec >> "$native_runtime_root/host-runner.log" 2>&1
    exec "$python_bin" "$native_repo_root/scripts/context_router_host_runner.py" \
      --control-url "$CONTEXT_ROUTER_CONTROL_URL" \
      --workspace-root "$CONTEXT_ROUTER_WORKSPACE_ROOT" \
      --runtime-root "$native_runtime_root" \
      --token-path "$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH" \
      --pid-path "$native_runner_pid"
    ;;
  frontend)
    print "$$" > "$native_frontend_pid"
    exec >> "$native_runtime_root/frontend.log" 2>&1
    cd "$native_repo_root/frontend"
    exec "$node_bin" node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 49175
    ;;
  *)
    print -u2 "未知 Native 服务：$service_name"
    exit 2
    ;;
esac
