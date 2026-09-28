#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

if (($# < 1)); then
  print -u2 "用法：run-managed-autostart.sh <命令> [参数...]"
  exit 1
fi

export PATH="/opt/homebrew/opt/node@22/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH}"
if [[ -n "${CONTEXT_ROUTER_HOST_TOOL_PATHS:-}" ]]; then
  export PATH="${CONTEXT_ROUTER_HOST_TOOL_PATHS}:$PATH"
fi

# Only readiness probes repeat, never the startup command. Each probe has a
# timeout, and failure after the finite wait exits before touching the stack.
/usr/bin/python3 - <<'PY'
import subprocess
import sys
import time
deadline = time.monotonic() + 60
while time.monotonic() < deadline:
    try:
        if subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=3).returncode == 0:
            break
    except (OSError, subprocess.TimeoutExpired):
        pass
    time.sleep(2)
else:
    print("Docker 未在 60 秒内就绪，本次登录启动结束，不自动重试。", file=sys.stderr)
    sys.exit(1)
PY

exec "$@"
