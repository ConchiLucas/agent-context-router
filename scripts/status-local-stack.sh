#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
repo_root=${script_dir:h}
runtime_root=${CONTEXT_ROUTER_RUNTIME_HOST_ROOT:-"$repo_root/.runtime-runner"}
control_url=${CONTEXT_ROUTER_CONTROL_URL:-"http://127.0.0.1:49173"}
pid_path="$runtime_root/runner.pid"
token_path="$runtime_root/runner.token"
runner_script="$repo_root/scripts/context_router_host_runner.py"

cd "$repo_root"
docker compose ps

if [[ ! -f "$pid_path" ]]; then
  print "Host Runtime Runner：未运行"
  exit 1
fi
runner_pid=$(<"$pid_path")
command_line=$(ps -p "$runner_pid" -o command= 2>/dev/null || true)
if [[ "$command_line" != *"$runner_script"* || "$command_line" != *"--runtime-root $runtime_root"* ]]; then
  print "Host Runtime Runner：PID 无效"
  exit 1
fi

if [[ ! -f "$token_path" ]]; then
  print "Host Runtime Runner：token 缺失"
  exit 1
fi
runner_token=$(<"$token_path")
if curl -fsS \
  -H "Authorization: Bearer $runner_token" \
  "$control_url/api/runtime-runner/status" | grep -q '"available":true'; then
  print "Host Runtime Runner：在线（PID=$runner_pid）"
else
  print "Host Runtime Runner：进程存在但心跳不可用（PID=$runner_pid）"
  exit 1
fi
unset runner_token
