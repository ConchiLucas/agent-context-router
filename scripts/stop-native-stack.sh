#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

native_stop_service "$native_launchd_frontend_label" "$native_frontend_pid" "node_modules/next/dist/bin/next start" "Frontend"
native_stop_service "$native_launchd_runner_label" "$native_runner_pid" "context_router_host_runner.py" "Host Runner"
native_stop_service "$native_launchd_backend_label" "$native_backend_pid" "context_router.main:create_app" "Backend"
print "已注册 Workspace 的 Docker 容器未被停止"
