#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
repo_root=${script_dir:h}
runtime_root=${CONTEXT_ROUTER_RUNTIME_HOST_ROOT:-"$repo_root/.runtime-runner"}
workspace_root=${CONTEXT_ROUTER_WORKSPACE_HOST_ROOT:-"/Users/conchi/workforce"}
control_url=${CONTEXT_ROUTER_CONTROL_URL:-"http://127.0.0.1:49173"}
token_path="$runtime_root/runner.token"
pid_path="$runtime_root/runner.pid"
runner_log="$runtime_root/host-runner.log"
runner_script="$repo_root/scripts/context_router_host_runner.py"

umask 077
mkdir -p "$runtime_root"
chmod 700 "$runtime_root"
if [[ ! -f "$token_path" ]]; then
  token_temp="$runtime_root/.runner.token.$$"
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))' > "$token_temp"
  chmod 600 "$token_temp"
  mv "$token_temp" "$token_path"
fi
chmod 600 "$token_path"

export CONTEXT_ROUTER_RUNTIME_HOST_ROOT="$runtime_root"
export CONTEXT_ROUTER_WORKSPACE_HOST_ROOT="$workspace_root"
cd "$repo_root"
docker compose up -d

health_ready=false
for _ in {1..60}; do
  if curl -fsS "$control_url/health" >/dev/null 2>&1; then
    health_ready=true
    break
  fi
  sleep 1
done
if [[ "$health_ready" != true ]]; then
  print -u2 "Context Router 后端健康检查超时"
  exit 1
fi

runner_matches() {
  local runner_pid="$1"
  local command_line
  if ! kill -0 "$runner_pid" 2>/dev/null; then
    return 1
  fi
  command_line=$(ps -p "$runner_pid" -o command= 2>/dev/null || true)
  [[ "$command_line" == *"$runner_script"* && "$command_line" == *"--runtime-root $runtime_root"* ]]
}

if [[ -f "$pid_path" ]]; then
  existing_pid=$(<"$pid_path")
  if runner_matches "$existing_pid"; then
    print "Host Runtime Runner 已在运行，PID=$existing_pid"
  elif kill -0 "$existing_pid" 2>/dev/null; then
    print -u2 "runner.pid 指向非本项目进程，拒绝覆盖：$existing_pid"
    exit 1
  else
    rm -f "$pid_path"
  fi
fi

if [[ ! -f "$pid_path" ]]; then
  nohup python3 "$runner_script" \
    --control-url "$control_url" \
    --workspace-root "$workspace_root" \
    --runtime-root "$runtime_root" \
    --token-path "$token_path" \
    >> "$runner_log" 2>&1 &
  runner_pid=$!
  pid_temp="$runtime_root/.runner.pid.$$"
  print -r -- "$runner_pid" > "$pid_temp"
  chmod 600 "$pid_temp"
  mv "$pid_temp" "$pid_path"
fi

runner_ready=false
runner_token=$(<"$token_path")
for _ in {1..30}; do
  if curl -fsS \
    -H "Authorization: Bearer $runner_token" \
    "$control_url/api/runtime-runner/status" | grep -q '"available":true'; then
    runner_ready=true
    break
  fi
  sleep 1
done
unset runner_token
if [[ "$runner_ready" != true ]]; then
  print -u2 "Host Runtime Runner 注册或心跳检查超时，请查看 $runner_log"
  exit 1
fi

print "Context Router 与 Host Runtime Runner 已就绪"
print "控制面：$control_url"
print "运行目录：$runtime_root"
