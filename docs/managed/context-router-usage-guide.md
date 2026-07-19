# Context Router 使用说明

本文件说明大模型如何按文档树使用 Context Router。

## 使用原则

- `ctx read <doc-id>` 是主流程，用来读取下一层或具体文档。
- `ctx prepare` 是兜底检索，只在不知道 doc-id 时使用。
- 每份索引文档都应该列出下一层文档、用途和 `ctx read` 示例。
- 调用链路由系统内部记录，AI 不需要传 traceId 或 reason。
- 源码、配置、表结构、日志等实时内容可以直接读取项目目录。

## 推荐流程

1. 从 `AGENTS.md` 或 `AI_CONTEXT_INDEX.md` 查看下一层文档清单。
2. 按任务选择一个 doc-id。
3. 运行 `ctx read <doc-id>`。
4. 如果读到的新文档还有下一层，继续按它列出的 doc-id 读取。
5. 如果文档树中没有合适内容，再使用 `ctx prepare --project <project>` 兜底检索。

## 下一层文档

| 文档 | 用途 | 命令 |
| --- | --- | --- |
| `context-router-read-guide` | 说明 `ctx read` 的使用边界 | `ctx read context-router-read-guide` |
| `context-router-trace-guide` | 说明调用记录如何自动保留 | `ctx read context-router-trace-guide` |
| `context-router-prepare-guide` | 说明兜底检索什么时候使用 | `ctx read context-router-prepare-guide` |
