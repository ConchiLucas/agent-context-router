# 上下文任务路由

调用 `prepare_task_context` 时通常只传 task 和 cwd。后端按 cwd 最长前缀选择已启用项目并返回该项目完整文档树，不根据 task 内容搜索、排名或只返回候选；下表用于 Agent 在返回树中选择后续要读的稳定文档。

| area | document_id | 适用任务 |
| --- | --- | --- |
| `startup` | `context-router-area-startup` | 启动、重启、测试、构建、migration |
| `database` | `context-router-area-database` | 控制面表结构、业务数据源、Connector、对象搜索和只读查询 |
| `frontend` | `context-router-area-frontend` | 页面、交互、浏览器验证 |
| `backend` | `context-router-area-backend` | API、MCP、数据库授权、Connector 和事件记录 |
| `business` | `context-router-area-business` | 产品目标、功能边界和 AI 工作流 |
| `debugging` | `context-router-area-debugging` | 异常、调用链和历史决策 |

项目 AGENTS.md 所在目录负责按 cwd 识别项目；多个项目都匹配时选择路径最长者。prepare 返回的 task_id 绑定该项目，后续文档和数据库调用不能通过参数切换项目。数据库再以该项目内 mcp_alias 精确路由，客户端不能提交连接信息绕过关联。
