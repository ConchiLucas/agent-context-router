# AGENTS.md

本文件是 AI 的短上下文索引。只列稳定文档、适用任务和下一层关系，不复制大段正文。

## Context Router 使用规则

- 任务依赖业务规则、启动、数据库或跨层链路时，调用 MCP `prepare_task_context(task, cwd, agent_name)`。
- prepare 返回当前映射项目的本 AGENTS.md 入口；先调用 `read_context_document(trace_id, document_id)` 读取它。
- 从本文档链接继续读取下一层时，必须传本入口的 `parent_document_id`；之后逐层传已读父文档。
- 明确文件或纯源码定位可以直接检索仓库，不强制调用 MCP。
- 不要一次读取全部文档。

## 文档索引

| document_id | 适用任务 | 下一层文档 |
| --- | --- | --- |
| `<doc-id>` | `<什么情况下需要这份文档>` | `<下一层 document_id，没有则留空>` |

## 维护规则

- 文档源放在统一挂载目录的项目子目录中：根 AGENTS.md 加 docs/**/*.md。
- project 的 root_path 必须覆盖 AI 传入的 cwd，docs_path 必须是 `/documents` 下直接子目录。
- 修改 Markdown 后在 Context Router 的 Projects 页面点击 **Sync Documents**。
- 文档 ID 和用途要稳定、具体，避免用“其他”“综合说明”等模糊描述。
