# Codex 与 Antigravity 双客户端验收包

本目录用于迁移后的真实 MCP 客户端验收，不参与线上检索，也不包含业务排序规则。

## 执行顺序

1. 将 `01-generate-private-gold-prompt.md` 原样交给一个只负责出题的全新模型。
2. 确认桌面生成私有金标和无答案题集，并且两份文件均为 50 题。
3. 将 `02-codex-execution-prompt.md` 交给全新 Codex 任务。
4. 将 `03-antigravity-execution-prompt.md` 交给全新 Antigravity 会话。
5. 两个客户端完成后执行：

```bash
cd /Users/conchi/workforce/python_workforce/agent-context-router/backend
.venv-native/bin/python scripts/score_interface_search_clients.py \
  --gold /Users/conchi/Desktop/Context-Router双客户端验收50题-私有金标.json \
  --result codex=/Users/conchi/Desktop/Context-Router双客户端验收50题-Codex结果.json \
  --result antigravity=/Users/conchi/Desktop/Context-Router双客户端验收50题-Antigravity结果.json \
  --output /Users/conchi/Desktop/Context-Router双客户端验收50题-评分报告.json
```

评分脚本同时生成同名 Markdown 报告。退出码为 `0` 表示两个客户端均达到门槛。

## 文件隔离

- 出题模型可以读取源码，但不得调用当前接口检索 MCP，也不得读取历史测评题集。
- 执行模型只能读取无答案题集并调用 Context Router MCP，不得读取源码、数据库、私有金标或历史报告。
- 私有金标只在最终评分时使用。
- 同一套题交给两个客户端，便于识别客户端调用策略差异。
