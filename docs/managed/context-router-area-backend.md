# 后端路由

## 适用任务

- FastAPI 内部 API、MCP 工具协议。
- cwd Workspace/active project 识别、显式根树/合成根树构建和 prepare/search/read 调用。
- task -> Workspace -> mcp_alias -> Project 授权的数据库路由、Connector 生命周期、SQL 安全和调用审计。

## 代码入口

| 路径 | 用途 |
| --- | --- |
| `backend/src/context_router/mcp_server.py` | prepare、文档搜索、read、对象搜索、只读查询五个固定工具 |
| `services/project_registry.py` | Workspace 根入口/Project 配置、cwd 匹配、显式/合成导航树、聚合文档读取缓存和原子刷新 |
| `services/context_preparation.py` | 创建 Workspace task_id，返回显式根树或合成根树、active project 和数据库授权摘要 |
| `services/context_document_search.py` | 校验 task Workspace 及 Workspace/Project 索引版本，聚合 PostgreSQL 文档搜索结果 |
| `services/markdown_search_parser.py` | 把 Markdown 解析为规范化、章节感知的检索分块 |
| `services/context_document_read.py` | 批量读取文档或章节并记录 read call |
| `services/database_access.py` | task/Workspace/mcp_alias 当前 Project 授权解析 |
| `services/database_catalog.py` | 渐进数据库对象搜索 |
| `services/database_query.py` | 有界只读 SQL 执行和审计 |
| `database/` | Connector Registry、Manager、SQL 策略和结果格式化 |
| `api/workspaces.py` | Workspace、Project 相对路径、聚合刷新/文档树和数据源汇总 API |
| `api/data_sources.py` | 数据源、数据库同步、能力、连接测试和 Project 授权 API |
| `api/tasks.py` | Workspace Task、文档读取和数据库调用历史 API |

产品层没有 CLI、反馈、任务成功评分或 Usage runtime。文档搜索使用控制面 PostgreSQL，不连接 Project 业务数据库；业务数据库连接在首次对象搜索/查询时延迟创建，prepare、文档 search 和 read 不依赖业务数据库在线。
