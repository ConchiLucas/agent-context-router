# 开发大纲

修改代码前先读取 [启动与开发规范](./STARTUP_GUIDE.md)，所有运行和验证均通过 Docker Compose。

## 任务路由

| 任务 | 文档 | 主要代码 |
| --- | --- | --- |
| 产品目标和文档格式 | [业务功能说明](./BUSINESS_FEATURES.md) | `services/document_tree.py` |
| 页面、API 和缓存链路 | [前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `project-dashboard.tsx`、`api/projects.py` |
| 启动、测试、lint、build | [启动与开发规范](./STARTUP_GUIDE.md) | `docker-compose.yml` |
| 数据库相关判断 | [数据库信息](./DATABASE_INFO.md) | `repositories/`、`migrations/` |
| 数据库 MCP 授权和 SQL 安全 | [业务功能说明](./BUSINESS_FEATURES.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/database_access.py`、`database/policy.py` |
| Connector 或 ClickHouse 集成 | [启动与开发规范](./STARTUP_GUIDE.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `database/connectors/`、`tests/test_clickhouse_integration.py` |

## 当前架构约束

- 根入口文件必须命名为 `AGENTS.md`。
- 文档层级只来自 `## 下级文档` 下的“功能说明 / 相对路径”表格。
- 映射由普通代码完成，不调用大模型。
- 项目名称、项目类型、AGENTS.md 路径和启停状态，以及独立的数据源分类与连接配置保存在 PostgreSQL；文档树和正文只保存在单个后端进程内，并在启动时从磁盘重建。
- 刷新是全量重建和原子替换。
- 前端只从树接口获取概览，从详情接口按需获取内存正文。
- 文档读取目录通过 Docker 只读挂载。
- MCP `tools/list` 固定为 prepare、read、数据库对象搜索和数据库只读查询四个工具，不按数据源动态注册工具。
- prepare 只读取本地项目、文档缓存和数据库授权摘要，不连接业务数据库；数据库访问统一按 `task_id -> project -> mcp_alias -> 当前策略 -> Connector` 路由。
- 项目数据库只有在项目、关联和数据源启用、数据库可用且非系统库、关联为只读、Engine 已实现 Connector 时才暴露给 MCP。
- MySQL、MariaDB、PostgreSQL、ClickHouse 当前实现发现、对象搜索和有界只读查询；SQL Server、SQLite、Oracle 仅保留配置管理。
- SQL 安全策略必须 fail-closed：只允许单条、可解析、限定当前数据库/Schema 的只读语句；不能把客户端 LIMIT 当作唯一边界，仍需服务端行数、字节数、超时和数据库侧只读限制。
- Connector 延迟创建且生命周期只归 `ConnectorManager`；数据源配置版本变化或删除时必须失效旧连接，应用退出时统一关闭。
- 数据库调用历史只保存客观元数据和 SQL SHA-256，不保存完整 SQL、参数或结果集。
- Context Router 四个 MCP 工具在统一分发入口记录到 `mcp_tool_calls`；任务内顺序由 PostgreSQL 调用 ID 生成，文档/数据库专属明细通过 `tool_call_id` 关联，观测失败不得改变工具业务结果。
- 当前链路管理的自动观测范围仅限 Context Router MCP。其他 MCP Server 只有在未来经过 Gateway 或显式传播 Trace 上下文时才能进入同一任务链路。
- 本地服务默认只绑定回环地址；真实 ClickHouse 测试使用根 Compose 的 `integration` profile 和固定镜像版本。
