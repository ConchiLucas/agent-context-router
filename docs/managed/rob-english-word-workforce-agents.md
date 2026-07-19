# rob-english-word-workforce AI 入口

这是多项目 workspace 的稳定索引。AI 应按任务选择文档，不要一次读取全部内容。

| document_id | 适用任务 |
| --- | --- |
| `rob-english-word-workforce-subprojects-overview` | 先了解有哪些子项目及各自职责 |
| `rob-english-word-workforce-database-info` | PostgreSQL、Redis、库名端口和数据排查 |
| `rob-english-word-workforce-flow-overview` | 用户侧、后台、Java、Go 和 Python agent 的跨服务流转 |
| `rob-english-word-workforce-ai-context-index` | 进一步按 startup/database/frontend/backend/business/debugging 路由 |

通过 MCP prepare 得到 trace_id 后，只对需要的 document_id 调用 read；源码和实时配置直接检查对应子项目。
