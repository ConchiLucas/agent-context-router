# 后端路由

## 适用任务

- FastAPI 内部 API、MCP 工具协议。
- cwd 项目识别、文档树构建和 prepare/read 调用。
- task -> project -> mcp_alias 数据库授权、Connector 生命周期、SQL 安全和调用审计。

## 代码入口

| 路径 | 用途 |
| --- | --- |
| `backend/src/context_router/mcp_server.py` | prepare、read、对象搜索、只读查询四个固定工具 |
| `services/project_registry.py` | 项目配置、cwd 最长前缀匹配和内存文档缓存 |
| `services/context_preparation.py` | 创建 task_id，返回完整文档树和本地数据库授权摘要 |
| `services/context_document_read.py` | 批量读取文档或章节并记录 read call |
| `services/database_access.py` | task/project/mcp_alias 当前授权解析 |
| `services/database_catalog.py` | 渐进数据库对象搜索 |
| `services/database_query.py` | 有界只读 SQL 执行和审计 |
| `database/` | Connector Registry、Manager、SQL 策略和结果格式化 |
| `api/data_sources.py` | 数据源、数据库同步、能力、连接测试和项目关联 API |
| `api/tasks.py` | Task、文档读取和数据库调用历史 API |

产品层没有 CLI、反馈、任务成功评分或 Usage runtime。业务数据库连接在首次搜索/查询时延迟创建，prepare 和文档 read 不依赖业务数据库在线。
