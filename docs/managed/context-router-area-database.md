# 数据库路由

## 适用任务

- PostgreSQL 连接、端口和权限。
- Alembic migration、表结构或数据检查。
- `document_projects`、`data_sources`、`data_source_databases`、`project_databases` 数据问题。
- `mcp_tasks`、文档 read call/item 和 `mcp_database_calls` 审计问题。
- MySQL、MariaDB、PostgreSQL、ClickHouse Connector、能力矩阵或只读查询问题。

## 下一层文档

| document_id | 用途 |
| --- | --- |
| `context-router-database-info` | 数据库连接、表和 migration 信息 |
| `context-router-area-startup` | Docker Compose 和 migration 执行方式 |

控制面 PostgreSQL 与项目授权的业务数据库不同。业务数据库 MCP 路由固定为 `task_id -> project -> mcp_alias -> 当前 Link/Database/Source 状态与策略`；连接参数不会进入 MCP 参数或调用历史。
