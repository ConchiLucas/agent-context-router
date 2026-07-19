# Context Router MCP 使用说明

## AI 使用原则

- 新窗口遇到业务规则、启动、数据库或跨层链路任务时，调用 `prepare_task_context(task, cwd, agent_name)`。
- 最多返回 3 份候选文档；只读取任务真正需要的内容。
- 读取时调用 `read_context_document(trace_id, document_id)`。
- 从已读文档继续向下时，补充 `parent_document_id`。
- 明确文件、符号或纯源码定位可以直接检索项目目录。
- MCP 没有合适候选时继续正常完成任务，不要求说明停止原因。

## 下一层文档

| document_id | 适用任务 |
| --- | --- |
| `context-router-prepare-guide` | 需要了解 prepare 参数、项目识别和候选限制 |
| `context-router-read-guide` | 需要了解显式 trace 阅读和父子链路 |
| `context-router-trace-guide` | 需要理解 Tasks 页面记录了什么 |
| `context-router-routing-guide` | 需要按 startup/database/frontend/backend/business/debugging 路由 |
