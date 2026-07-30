# 开发大纲

修改代码前先读取 [启动与开发规范](./STARTUP_GUIDE.md)，所有运行和验证均通过 Docker Compose。

## 任务路由

| 任务 | 文档 | 主要代码 |
| --- | --- | --- |
| 产品目标、文档格式和全文检索 | [业务功能说明](./BUSINESS_FEATURES.md) | `services/document_tree.py`、`services/document_search.py` |
| 工作空间/项目管理、页面、API 和缓存链路 | [业务功能说明](./BUSINESS_FEATURES.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `workspace-dashboard.tsx`、`workspace-detail.tsx`、`api/workspaces.py`、`services/project_registry.py` |
| 启动、测试、lint、build | [启动与开发规范](./STARTUP_GUIDE.md) | `docker-compose.yml` |
| 工作空间/项目持久化和数据库相关判断 | [数据库信息](./DATABASE_INFO.md) | `workspace_repository.py`、`project_repository.py`、`migrations/` |
| 数据库 MCP 授权和 SQL 安全 | [业务功能说明](./BUSINESS_FEATURES.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/database_access.py`、`database/policy.py` |
| Connector 或 ClickHouse 集成 | [启动与开发规范](./STARTUP_GUIDE.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `database/connectors/`、`tests/test_clickhouse_integration.py` |

## 当前架构约束

- Workspace 和 Project 的根入口文件必须命名为 `AGENTS.md`；Workspace 根入口可选，缺失时使用合成根。新 Project 的入口统一配置在 Workspace 的 `docs/` 层级下。
- 文档层级只来自 `## 下级文档` 下的“功能说明 / 相对路径”表格。存在真实 Workspace 根 `AGENTS.md` 时，展示树和 prepare 文档树严格保留其显式父子关系，不自动把 Project 根入口追加为直接下级；缺少真实根时，合成根才直接列出各 Project 入口。
- 映射由普通代码完成，不调用大模型。
- Workspace 是顶层目录、Codex task 和运行时上下文边界；根目录存在 `AGENTS.md` 时作为工作空间级文档入口。Project 必须属于一个 Workspace，保存名称、`frontend/backend` 类型、源码 `relative_path` 和文档入口 `document_relative_path`，没有独立 enabled。源码根项目使用 `.`；项目文档入口由 `workspace.root_path / document_relative_path` 推导，兼容 `agents_path` 只作为绝对路径镜像。
- 工作空间根目录必须是绝对路径；项目源码和文档入口相对路径都禁止绝对路径、`~`、反斜杠和 `..`，解析后不能通过软链接越出工作空间，同一工作空间内两类路径分别唯一。新文档入口必须位于 `docs/` 下并以 `AGENTS.md` 结尾。
- 工作空间/项目配置，以及独立的数据源分类与连接配置保存在 PostgreSQL；文档树和 Markdown 原文只保存在单个后端进程内并在启动时从磁盘重建，PostgreSQL 分别保存可重建的 Workspace/Project 规范化检索分块和版本状态。
- 物理数据源配置全局共享，数据库授权继续由 `project_databases` 绑定具体 Project；Workspace task 汇总使用所有子项目当前有效的授权，`mcp_alias` 在整个 Workspace 内大小写无关唯一。
- 可选的 Workspace 数据库环境映射把同一逻辑别名分别绑定到 TEST/UAT 的项目数据库关联。`prepare_task_context` 可选传 `environment='test'|'uat'`：显式值只固定本 task 的 `task_explicit` 环境，不修改 Workspace 当前环境；省略时固化当前环境并记录为 `workspace_default`。两种模式都保存共享 revision，revision 变化后旧 task 必须重新 prepare，禁止静默换库。
- 没有配置环境选择器的单环境 Workspace 继续使用原有 Workspace alias 链路；省略 `environment` 保持旧行为，显式传入时返回 `environment_not_configured`，不得猜测或自动创建选择器。
- 同一 Workspace 环境选择器还可分别保存 TEST/UAT JSON 对象，用于 MQ、Redis、MinIO、ES、任务调度或未来组件的环境差异；JSON 不预设字段且可独立于数据库映射启用选择器。可按明确业务需要保存地址和访问凭据，但内容以明文 JSONB 保存在本地，所选环境的 `environment_config` 只随 prepare 返回给可信本机 MCP 调用方，严禁进入日志、开发文档、链路摘要或示例输出。两份 JSON 合计最多 256 KiB、最多嵌套 20 层。
- 刷新以 Workspace 为单位全量重建可选根入口和全部子项目并统一替换；会遍历并记录全部失败项目，任一入口文档构建失败时仍保留上一版工作空间映射。
- 前端只从 Workspace 树接口获取显式根树或合成根树，从 Workspace 文档详情接口按需获取内存正文；未出现在真实根显式树中的 Project 文档仍保留在 Workspace 搜索和按 ID 读取范围。
- 文档读取目录通过 Docker 只读挂载。
- MCP `tools/list` 固定为 prepare、文档搜索、read、数据库对象搜索和数据库只读查询五个工具，不按项目或数据源动态注册工具。
- 新 task 的文档搜索固定绑定 Workspace，查询工作空间根文档独立索引及各 Project 同版本索引，再聚合去重；索引不可用时显式失败，不回退到进程内全文扫描。
- cwd 路由先按最长前缀选择最深 Workspace，再按 Project 的源码根而不是文档入口目录选择最深 Project；`active_project` 只作为元数据，不收窄 Workspace 的文档和数据库范围。Workspace 停用或任一项目缓存不可用时 prepare 明确失败。
- prepare 返回 Workspace 元数据、全部 Project 的类型/相对路径、显式根树或合成根树和全工作空间数据库摘要，但不连接业务数据库；全部 Project 文档继续通过 Workspace 搜索和按 ID 读取访问。数据库访问统一按 `task_id -> workspace snapshot -> workspace mcp_alias -> 当前项目授权/连接/策略 -> Connector` 路由。
- 项目数据库只有在工作空间、关联和数据源启用、数据库可用且非系统库、关联为只读、Engine 已实现 Connector 时才暴露给 Workspace task；Project 本身没有启停状态。
- MySQL、MariaDB、PostgreSQL、ClickHouse 当前实现发现、对象搜索和有界只读查询；SQL Server、SQLite、Oracle 仅保留配置管理。
- SQL 安全策略必须 fail-closed：只允许单条、可解析、限定当前数据库/Schema 的只读语句；不能把客户端 LIMIT 当作唯一边界，仍需服务端行数、字节数、超时和数据库侧只读限制。
- Connector 延迟创建且生命周期只归 `ConnectorManager`；数据源配置版本变化或删除时必须失效旧连接，应用退出时统一关闭。
- `mcp_database_calls` 审计历史只保存客观元数据和 SQL SHA-256；两个数据库 MCP 工具另以独立、可过期的有界 JSON 快照保存实际请求和最终 MCP 响应，主 Trace 接口不内联这些大字段。
- Context Router 五个 MCP 工具在统一分发入口记录到 `mcp_tool_calls`；任务内顺序由 PostgreSQL 调用 ID 生成，文档/数据库专属明细通过 `tool_call_id` 关联，观测失败不得改变工具业务结果。
- 链路管理只记录 Codex、Antigravity 等客户端实际发送到 Context Router `/mcp` 的五个内部工具调用；不连接、代理、聚合或接收其他 MCP Server 的调用上报，也不建设跨 Server Trace。
- 顶层页面管理 Workspace；进入详情后使用“前端项目 / 后端项目 / 数据源汇总”三页签。环境映射、刷新映射、查看调用记录、查看文档树和查看 MCP JSON 都位于 Workspace 工具栏；前端项目不显示数据库授权入口，后端项目继续维护项目级数据源授权。
- 完整出入参只对白名单数据库工具 `search_database_objects`、`execute_database_query` 自动采集，并通过 no-store 详情 API 懒加载；prepare/search/read 不建立完整 payload 快照。
- 新 task 使用 `scope='workspace'` 和无外键的稳定 Workspace/活动项目快照；`scope='project'` 的旧 task 继续按原 project_id/project_key 读取、搜索和解析数据库，避免升级后历史串链。后端启动会收敛遗留 running 调用，Trace API 与页面明确区分完整、运行中和可能不完整。
- migration head 为 `20260730_0021`；`0013` 把旧 Project 升级为同 ID Workspace 下 `relative_path='.'` 的根项目，`0014` 增加 `project_kind`、删除 Project enabled、提升 alias 唯一范围并增加 Workspace task 快照，`0015` 增加工作空间级文档派生搜索索引，`0016` 拆分源码相对路径和文档入口相对路径，`0017` 增加项目快速/完整更新的运行配置文件，`0018` 增加 Runtime Runner 异步执行记录，`0019` 增加 Workspace TEST/UAT 数据库映射、当前环境和 task 环境 revision，`0020` 增加按环境保存的通用 JSON，`0021` 为 task 增加 `database_environment_selection`，并把已有非空环境 task 回填为 `workspace_default`。旧项目 ID、数据库授权和调用历史保持不变。
- 本地服务默认只绑定回环地址；真实 ClickHouse 测试使用根 Compose 的 `integration` profile 和固定镜像版本。
