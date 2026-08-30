#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

status_code=0
if native_service_running "$native_launchd_backend_label" "$native_backend_pid" "context_router.main:create_app" && \
  curl -fsS "$CONTEXT_ROUTER_CONTROL_URL/health" >/dev/null 2>&1; then
  print "Backend：在线"
else
  print "Backend：离线"
  status_code=1
fi

if native_service_running "$native_launchd_frontend_label" "$native_frontend_pid" "node_modules/next/dist/bin/next start" && \
  curl -fsS "http://127.0.0.1:49175" >/dev/null 2>&1; then
  print "Frontend：在线"
else
  print "Frontend：离线"
  status_code=1
fi

if native_service_running "$native_launchd_runner_label" "$native_runner_pid" "context_router_host_runner.py"; then
  runner_token=$(<"$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH")
  if curl -fsS -H "Authorization: Bearer $runner_token" \
    "$CONTEXT_ROUTER_CONTROL_URL/api/runtime-runner/status" | grep -q '"available":true'; then
    print "Host Runner：在线"
  else
    print "Host Runner：进程存在但心跳不可用"
    status_code=1
  fi
  unset runner_token
else
  print "Host Runner：离线"
  status_code=1
fi

if docker info >/dev/null 2>&1; then
  print "Docker Engine：在线（供已注册 Workspace 使用）"
else
  print "Docker Engine：离线"
  status_code=1
fi

exit "$status_code"
