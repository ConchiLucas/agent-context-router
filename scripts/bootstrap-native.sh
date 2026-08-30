#!/bin/zsh
set -euo pipefail

source "${0:A:h}/native-common.sh"

native_require_command python3
native_require_command uv
native_require_node22
native_require_command node
native_require_command npm
native_require_command docker
native_require_command curl

if ! uv python find 3.12 >/dev/null 2>&1; then
  print -u2 "找不到 Python 3.12；请先执行 uv python install 3.12"
  exit 1
fi

docker info >/dev/null
native_prepare_runtime

cd "$native_repo_root/backend"
uv sync --extra dev --python 3.12

cd "$native_repo_root/frontend"
npm ci

print "Native 依赖和运行目录已准备完成"
print "请确认配置文件：$native_env_file"
