# 上下文任务路由

调用 `prepare_task_context` 时通常只传 task 和 cwd，后端根据内容匹配下列稳定文档。

| area | document_id | 适用任务 |
| --- | --- | --- |
| `startup` | `context-router-area-startup` | 启动、重启、测试、构建、migration |
| `database` | `context-router-area-database` | 连接、表结构、数据检查 |
| `frontend` | `context-router-area-frontend` | 页面、交互、浏览器验证 |
| `backend` | `context-router-area-backend` | API、MCP、检索和事件记录 |
| `business` | `context-router-area-business` | 产品目标、功能边界和 AI 工作流 |
| `debugging` | `context-router-area-debugging` | 异常、调用链和历史决策 |

项目 root path 负责按 cwd 识别项目；父项目检索可以覆盖子项目文档。
