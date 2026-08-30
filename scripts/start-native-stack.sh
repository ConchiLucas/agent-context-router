#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

native_require_command uv
native_require_node22
native_require_command npm
native_require_command python3
native_require_command curl
native_require_command docker
native_prepare_runtime
uv_bin=$(command -v uv)
python_bin=$(command -v python3)
node_bin=$(command -v node)

native_start_succeeded=false
native_cleanup_failed_start() {
  if [[ "$native_start_succeeded" != true ]]; then
    "$native_repo_root/scripts/stop-native-stack.sh" >/dev/null 2>&1 || true
  fi
}
trap native_cleanup_failed_start EXIT

if [[ -z "${CONTEXT_ROUTER_DATABASE_URL:-}" ]]; then
  print -u2 "CONTEXT_ROUTER_DATABASE_URL 未配置"
  exit 1
fi
docker info >/dev/null

if native_service_running "$native_launchd_backend_label" "$native_backend_pid" "context_router.main:create_app"; then
  print -u2 "Backend 已在运行"
  exit 1
fi
if native_service_running "$native_launchd_frontend_label" "$native_frontend_pid" "node_modules/next/dist/bin/next start"; then
  print -u2 "Frontend 已在运行"
  exit 1
fi
if native_service_running "$native_launchd_runner_label" "$native_runner_pid" "context_router_host_runner.py"; then
  print -u2 "Host Runner 已在运行"
  exit 1
fi

cd "$native_repo_root/backend"
uv run alembic upgrade head
if native_launchd_available; then
  launchctl submit -l "$native_launchd_backend_label" -- \
    "$native_repo_root/scripts/run-native-service.sh" backend "$uv_bin" "$python_bin" "$node_bin"
else
  nohup "$native_repo_root/scripts/run-native-service.sh" backend "$uv_bin" "$python_bin" "$node_bin" >/dev/null 2>&1 &
fi
if ! native_wait_http "$CONTEXT_ROUTER_CONTROL_URL/health" "Backend"; then
  exit 1
fi

if native_launchd_available; then
  launchctl submit -l "$native_launchd_runner_label" -- \
    "$native_repo_root/scripts/run-native-service.sh" runner "$uv_bin" "$python_bin" "$node_bin"
else
  nohup "$native_repo_root/scripts/run-native-service.sh" runner "$uv_bin" "$python_bin" "$node_bin" >/dev/null 2>&1 &
fi

runner_ready=false
runner_token=$(<"$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH")
for _ in {1..30}; do
  if curl -fsS -H "Authorization: Bearer $runner_token" \
    "$CONTEXT_ROUTER_CONTROL_URL/api/runtime-runner/status" | grep -q '"available":true'; then
    runner_ready=true
    break
  fi
  sleep 1
done
unset runner_token
if [[ "$runner_ready" != true ]]; then
  print -u2 "Host Runner 启动检查失败，请查看 $native_runtime_root/host-runner.log"
  "$native_repo_root/scripts/stop-native-stack.sh" || true
  exit 1
fi

cd "$native_repo_root/frontend"
npm run build:native
if native_launchd_available; then
  launchctl submit -l "$native_launchd_frontend_label" -- \
    "$native_repo_root/scripts/run-native-service.sh" frontend "$uv_bin" "$python_bin" "$node_bin"
else
  nohup "$native_repo_root/scripts/run-native-service.sh" frontend "$uv_bin" "$python_bin" "$node_bin" >/dev/null 2>&1 &
fi
if ! native_wait_http "http://127.0.0.1:49175" "Frontend"; then
  "$native_repo_root/scripts/stop-native-stack.sh" || true
  exit 1
fi

print "Context Router Native Stack 已就绪"
print "Web：http://127.0.0.1:49175"
print "API：$CONTEXT_ROUTER_CONTROL_URL"
print "MCP：$CONTEXT_ROUTER_PUBLIC_MCP_URL"
native_start_succeeded=true
