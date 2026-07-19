# Tasks 调用链说明

## 记录内容

- task、cwd、project、agent_name 和创建时间。
- prepare 返回的候选文档、rank、score 和 reason。
- AI 实际调用 read 的 document_id、parent_document_id、depth。
- prepare/read 的服务端 duration_ms。

## 页面含义

- `Read by AI`：候选文档随后出现 read 事件。
- `Returned only`：文档被返回，但 AI 没有读取全文。
- Tasks 外层列表只展示 MCP 来源任务。

系统不记录人工反馈，也不推测 AI 为什么没有继续阅读。开发者可通过长期链路分布判断文档标题、标签、拆分或路由是否需要优化。
