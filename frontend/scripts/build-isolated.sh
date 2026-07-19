#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build_dir=$(mktemp -d /tmp/agent-context-router-next-build.XXXXXX)

cleanup() {
  case "$build_dir" in
    /tmp/agent-context-router-next-build.*)
      rm -rf -- "$build_dir"
      ;;
  esac
}
trap cleanup EXIT HUP INT TERM

cp -R \
  "$project_dir/app" \
  "$project_dir/components" \
  "$project_dir/lib" \
  "$build_dir/"
cp \
  "$project_dir/eslint.config.mjs" \
  "$project_dir/next-env.d.ts" \
  "$project_dir/next.config.ts" \
  "$project_dir/package.json" \
  "$project_dir/tsconfig.json" \
  "$build_dir/"
ln -s "$project_dir/node_modules" "$build_dir/node_modules"

cd "$build_dir"
"$project_dir/node_modules/.bin/next" build
