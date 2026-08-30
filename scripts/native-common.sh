#!/bin/zsh

set -euo pipefail

native_script_dir=${0:A:h}
native_repo_root=${native_script_dir:h}
native_env_file=${CONTEXT_ROUTER_NATIVE_ENV_FILE:-"$native_repo_root/.env.native.local"}

if [[ -f "$native_env_file" ]]; then
  set -a
  source "$native_env_file"
  set +a
fi

export CONTEXT_ROUTER_RUNTIME_MODE=native
export CONTEXT_ROUTER_WORKSPACE_ROOT=${CONTEXT_ROUTER_WORKSPACE_ROOT:-"/Users/conchi/workforce"}
export CONTEXT_ROUTER_WORKSPACE_MAPPING_FILE=${CONTEXT_ROUTER_WORKSPACE_MAPPING_FILE:-"$native_repo_root/.context-router/workspaces.local.yaml"}
export CONTEXT_ROUTER_RUNTIME_ROOT=${CONTEXT_ROUTER_RUNTIME_ROOT:-"$native_repo_root/.runtime-runner"}
export CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH=${CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH:-"$CONTEXT_ROUTER_RUNTIME_ROOT/runner.token"}
export CONTEXT_ROUTER_PUBLIC_MCP_URL=${CONTEXT_ROUTER_PUBLIC_MCP_URL:-"http://127.0.0.1:49173/mcp"}
export CONTEXT_ROUTER_INTERNAL_MCP_URL=${CONTEXT_ROUTER_INTERNAL_MCP_URL:-"http://127.0.0.1:49173/mcp"}
export CONTEXT_ROUTER_CONTROL_URL=${CONTEXT_ROUTER_CONTROL_URL:-"http://127.0.0.1:49173"}
export NEXT_PUBLIC_CONTEXT_ROUTER_API_URL=${NEXT_PUBLIC_CONTEXT_ROUTER_API_URL:-"http://127.0.0.1:49173"}
export CONTEXT_ROUTER_INTERNAL_API_URL=${CONTEXT_ROUTER_INTERNAL_API_URL:-"http://127.0.0.1:49173"}
export CONTEXT_ROUTER_RUNTIME_EXECUTION_ENABLED=false
export CONTEXT_ROUTER_RUNTIME_RUNNER_API_ENABLED=true
export UV_PROJECT_ENVIRONMENT=${UV_PROJECT_ENVIRONMENT:-"$native_repo_root/backend/.venv-native"}

# Native control-plane calls must never leave the host through a configured proxy.
native_no_proxy=${NO_PROXY:-${no_proxy:-}}
if [[ ",$native_no_proxy," != *",127.0.0.1,"* ]]; then
  native_no_proxy="${native_no_proxy:+$native_no_proxy,}127.0.0.1"
fi
if [[ ",$native_no_proxy," != *",localhost,"* ]]; then
  native_no_proxy="${native_no_proxy:+$native_no_proxy,}localhost"
fi
export NO_PROXY=$native_no_proxy
export no_proxy=$native_no_proxy

native_runtime_root=$CONTEXT_ROUTER_RUNTIME_ROOT
native_backend_pid="$native_runtime_root/backend.pid"
native_frontend_pid="$native_runtime_root/frontend.pid"
native_runner_pid="$native_runtime_root/runner.pid"
native_launchd_backend_label="com.agent-context-router.native.backend"
native_launchd_frontend_label="com.agent-context-router.native.frontend"
native_launchd_runner_label="com.agent-context-router.native.runner"

native_require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    print -u2 "缺少命令：$1"
    return 1
  fi
}

native_require_node22() {
  local candidate
  for candidate in \
    "${CONTEXT_ROUTER_NODE_HOME:-}/bin/node" \
    "/opt/homebrew/opt/node@22/bin/node" \
    "/usr/local/opt/node@22/bin/node" \
    "$(command -v node 2>/dev/null || true)"; do
    [[ -n "$candidate" && -x "$candidate" ]] || continue
    if [[ "$($candidate -p 'process.versions.node.split(".")[0]')" == "22" ]]; then
      export PATH="${candidate:h}:$PATH"
      return 0
    fi
  done
  print -u2 "需要 Node.js 22；macOS Homebrew 可执行：brew install node@22"
  return 1
}

native_prepare_runtime() {
  umask 077
  mkdir -p "$native_runtime_root"
  chmod 700 "$native_runtime_root"
  if [[ ! -f "$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH" ]]; then
    local token_temp="$native_runtime_root/.runner.token.$$"
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$token_temp"
    chmod 600 "$token_temp"
    mv "$token_temp" "$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH"
  fi
  chmod 600 "$CONTEXT_ROUTER_RUNTIME_RUNNER_TOKEN_PATH"
}

native_pid_matches() {
  local pid_path=$1
  local marker=$2
  [[ -f "$pid_path" ]] || return 1
  local process_id
  process_id=$(<"$pid_path")
  [[ "$process_id" == <-> ]] || return 1
  kill -0 "$process_id" 2>/dev/null || return 1
  local command_line
  command_line=$(ps -p "$process_id" -o command= 2>/dev/null || true)
  [[ "$command_line" == *"$marker"* ]]
}

native_wait_http() {
  local url=$1
  local label=$2
  local attempts=${3:-60}
  local attempt=0
  while (( attempt < attempts )); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  print -u2 "$label 启动健康检查超时：$url"
  return 1
}

native_stop_pid() {
  local pid_path=$1
  local marker=$2
  local label=$3
  if [[ ! -f "$pid_path" ]]; then
    print "$label：未运行"
    return 0
  fi
  local process_id
  process_id=$(<"$pid_path")
  if ! native_pid_matches "$pid_path" "$marker"; then
    if kill -0 "$process_id" 2>/dev/null; then
      print -u2 "$label PID 指向非本项目进程，拒绝停止：$process_id"
      return 1
    fi
    rm -f "$pid_path"
    print "$label：未运行"
    return 0
  fi
  kill -TERM "$process_id"
  for _ in {1..50}; do
    if ! kill -0 "$process_id" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
  if kill -0 "$process_id" 2>/dev/null; then
    kill -KILL "$process_id"
  fi
  rm -f "$pid_path"
  print "$label：已停止"
}

native_launchd_available() {
  [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1
}

native_launchd_running() {
  launchctl print "gui/$(id -u)/$1" >/dev/null 2>&1
}

native_service_running() {
  local label=$1
  local pid_path=$2
  local marker=$3
  if native_launchd_available && native_launchd_running "$label"; then
    return 0
  fi
  native_pid_matches "$pid_path" "$marker"
}

native_stop_service() {
  local label=$1
  local pid_path=$2
  local marker=$3
  local name=$4
  if native_launchd_available && native_launchd_running "$label"; then
    launchctl remove "$label"
    rm -f "$pid_path"
    print "$name：已停止"
    return 0
  fi
  native_stop_pid "$pid_path" "$marker" "$name"
}
