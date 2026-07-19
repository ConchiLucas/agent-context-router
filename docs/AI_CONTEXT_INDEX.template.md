# AI_CONTEXT_INDEX.md

本文件是 AI 的短上下文索引。只列稳定文档、适用任务和下一层关系，不复制大段正文。

## Context Router 使用规则

- 任务依赖业务规则、启动、数据库或跨层链路时，调用 MCP `prepare_task_context(task, cwd, agent_name)`。
- 从最多 3 份候选文档中选择需要的内容，再调用 `read_context_document(trace_id, document_id)`。
- 从一份文档继续读取下一层时，传 `parent_document_id`。
- 明确文件或纯源码定位可以直接检索仓库，不强制调用 MCP。
- 不要一次读取全部文档。

## 文档索引

| document_id | 适用任务 | 下一层文档 |
| --- | --- | --- |
| `<doc-id>` | `<什么情况下需要这份文档>` | `<下一层 document_id，没有则留空>` |

## 维护规则

- 文档源放在各自项目仓库。
- project 的 root path 必须能覆盖 AI 传入的 cwd。
- 修改 Markdown 后在 Context Router 的 Projects 页面点击 **Sync Documents**。
- 文档 ID 和用途要稳定、具体，避免用“其他”“综合说明”等模糊描述。
