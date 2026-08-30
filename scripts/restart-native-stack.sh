#!/bin/zsh
set -euo pipefail

script_dir=${0:A:h}
"$script_dir/stop-native-stack.sh"
"$script_dir/start-native-stack.sh"
