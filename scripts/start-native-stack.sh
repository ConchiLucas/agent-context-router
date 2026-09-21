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

native_ensure_shared_config() {
  follow_flag="$native_runtime_root/managed-scripts/shared-config-center.follow"
  if [[ -f "$follow_flag" && "$(<"$follow_flag")" == "0" ]]; then
    return 0
  fi
  if ! "$native_repo_root/scripts/ensure-shared-config-center.sh"; then
    print -u2 "共享配置中心未就绪，配置管理页将无法读取数据库配置"
  fi
}

native_ensure_personal_utils() {
  follow_flag="$native_runtime_root/managed-scripts/personal-utils.follow"
  if [[ -f "$follow_flag" && "$(<"$follow_flag")" == "0" ]]; then
    return 0
  fi
  if ! "$native_repo_root/scripts/ensure-personal-utils.sh"; then
    print -u2 "Personal Utils Hub 未就绪"
  fi
}

native_ensure_panzhihua_host_runtime() {
  local listing workspace_id response operation_id operation_status

  if ! listing=$(curl -fsS "$CONTEXT_ROUTER_CONTROL_URL/api/managed-scripts"); then
    print -u2 "无法读取攀枝花 Host Runtime 跟随配置"
    return 0
  fi
  workspace_id=$(print -r -- "$listing" | "$python_bin" -c '
import json
import sys

payload = json.load(sys.stdin)
for item in payload.get("scripts", []):
    if (
        item.get("slug") == "panzhihua-host-runtime"
        and item.get("autostart_enabled") is True
        and item.get("available") is True
    ):
        print(item.get("workspace_id") or "")
        break
' 2>/dev/null) || {
    print -u2 "无法解析攀枝花 Host Runtime 跟随配置"
    return 0
  }
  [[ -n "$workspace_id" ]] || return 0

  if ! response=$(curl -fsS -X POST \
    -H "Content-Type: application/json" \
    --data '{"action":"pzh.ensure-host-runtime","environment":"local"}' \
    "$CONTEXT_ROUTER_CONTROL_URL/api/workspaces/$workspace_id/host-runtime/actions"); then
    print -u2 "攀枝花 Host Runtime 跟随 Context Router 启动失败：无法提交保障任务"
    return 0
  fi
  operation_id=$(print -r -- "$response" | "$python_bin" -c '
import json
import sys

print(json.load(sys.stdin).get("id", ""))
' 2>/dev/null) || true
  if [[ -z "$operation_id" ]]; then
    print -u2 "攀枝花 Host Runtime 跟随 Context Router 启动失败：未返回任务 ID"
    return 0
  fi

  print "等待攀枝花 Host Runtime 完成：$operation_id"
  for _ in {1..180}; do
    operation_status=$(curl -fsS \
      "$CONTEXT_ROUTER_CONTROL_URL/api/workspaces/$workspace_id/runtime-operations/$operation_id" 2>/dev/null | \
      "$python_bin" -c '
import json
import sys

print(json.load(sys.stdin).get("status", ""))
' 2>/dev/null) || operation_status=""
    case "$operation_status" in
      succeeded)
        print "[PASS] 攀枝花 Host Runtime 已跟随 Context Router 启动"
        return 0
        ;;
      failed|interrupted)
        print -u2 "攀枝花 Host Runtime 跟随启动未完成：$operation_status（任务 $operation_id）"
        return 0
        ;;
    esac
    sleep 1
  done
  print -u2 "攀枝花 Host Runtime 跟随启动等待超时（任务 $operation_id）"
}

native_ensure_shared_config
native_ensure_personal_utils

if native_service_running "$native_launchd_backend_label" "$native_backend_pid" "context_router.main:create_app" && \
  native_service_running "$native_launchd_frontend_label" "$native_frontend_pid" "node_modules/next/dist/bin/next start" && \
  native_service_running "$native_launchd_runner_label" "$native_runner_pid" "context_router_host_runner.py"; then
  native_ensure_panzhihua_host_runtime
  print "Context Router Native Stack 已在运行"
  native_start_succeeded=true
  exit 0
fi

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

native_ensure_panzhihua_host_runtime

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
