#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
repo_root=${script_dir:h}
runtime_root=${CONTEXT_ROUTER_RUNTIME_HOST_ROOT:-"$repo_root/.runtime-runner"}
pid_path="$runtime_root/runner.pid"
runner_script="$repo_root/scripts/context_router_host_runner.py"

if [[ -f "$pid_path" ]]; then
  runner_pid=$(<"$pid_path")
  if kill -0 "$runner_pid" 2>/dev/null; then
    command_line=$(ps -p "$runner_pid" -o command= 2>/dev/null || true)
    if [[ "$command_line" != *"$runner_script"* || "$command_line" != *"--runtime-root $runtime_root"* ]]; then
      print -u2 "runner.pid 指向非本项目进程，拒绝停止：$runner_pid"
      exit 1
    fi
    kill -TERM "$runner_pid"
    for _ in {1..50}; do
      if ! kill -0 "$runner_pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    if kill -0 "$runner_pid" 2>/dev/null; then
      kill -KILL "$runner_pid"
    fi
  fi
  rm -f "$pid_path"
  print "Host Runtime Runner 已停止"
else
  print "Host Runtime Runner 未运行"
fi

if [[ "${1:-}" == "--all" ]]; then
  cd "$repo_root"
  docker compose down
  print "Context Router Docker Compose 已停止"
fi
