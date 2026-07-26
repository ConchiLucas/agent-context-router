# 上下文任务路由

调用 `prepare_task_context` 时通常只传 task 和 cwd。后端按 cwd 最长前缀选择已启用 Workspace，返回真实根显式树或合成根树；cwd 落在某个 Project 时，再按最深相对路径标记 active project。prepare 不根据 task 内容搜索、排名或只返回候选；下表用于 Agent 在返回树中选择后续要读的稳定文档。树较大、无法直接判断或目标 Project 未进入显式树时，再用 prepare 返回的 task_id 调用 `search_context_documents`，定位命中文档/章节后调用 read。

| area | document_id | 适用任务 |
| --- | --- | --- |
| `startup` | `context-router-area-startup` | 启动、重启、测试、构建、migration |
| `database` | `context-router-area-database` | 控制面表结构、业务数据源、Connector、对象搜索和只读查询 |
| `frontend` | `context-router-area-frontend` | 页面、交互、浏览器验证 |
| `backend` | `context-router-area-backend` | API、MCP、数据库授权、Connector 和事件记录 |
| `business` | `context-router-area-business` | 产品目标、功能边界和 AI 工作流 |
| `debugging` | `context-router-area-debugging` | 异常、调用链和历史决策 |

Workspace 的 `root_path` 负责按 cwd 识别工作空间；Workspace 内最深匹配的 Project 相对路径只用于标记 active project，不缩小任务权限范围。prepare 返回的 task_id 绑定该 Workspace，后续文档和数据库调用不能通过参数切换 Workspace。数据库以 Workspace 内唯一的 mcp_alias 精确路由到具体 Project 授权，客户端不能提交连接信息绕过关联。
