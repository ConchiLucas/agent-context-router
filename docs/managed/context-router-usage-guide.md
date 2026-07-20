# Context Router MCP 使用说明

## AI 使用原则

- 新窗口遇到业务规则、启动、数据库或跨层链路任务时，调用 `prepare_task_context(task, cwd, agent_name)`。
- prepare 返回 cwd 对应项目的完整文档树；先用 title、summary 和 path 建立全局认知。
- 选择文档后调用 `read_context_document(task_id, requests)`；task_id 必须来自当前 prepare，不跨任务复用。
- requests 可同时包含多个 document_id 和可选 section，返回顺序严格保持输入顺序。
- 完整树不等于完整正文，不要一次读取所有 Markdown 内容。
- 明确文件、符号或纯源码定位可以直接检索项目目录。
- MCP 没有合适候选时继续正常完成任务，不要求说明停止原因。

## 下一层文档

| document_id | 适用任务 |
| --- | --- |
| `context-router-prepare-guide` | 需要了解 prepare 参数、项目识别和候选限制 |
| `context-router-read-guide` | 需要了解显式 trace 阅读和父子链路 |
| `context-router-trace-guide` | 需要理解 Tasks 页面记录了什么 |
| `context-router-routing-guide` | 需要按 startup/database/frontend/backend/business/debugging 路由 |
