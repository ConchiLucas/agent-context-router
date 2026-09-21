#!/bin/zsh
set -euo pipefail

# Retired: Docker Compose used to publish the old frontend on 49174.
# Keep the filename so leftover docs/muscle memory still land on Native Stack.
print "start-local-stack.sh 已停用，不再启动 Docker 前端/后端，也不再使用 49174"
print "改走 Native Stack：http://127.0.0.1:49175"
exec "${0:A:h}/start-native-stack.sh"
