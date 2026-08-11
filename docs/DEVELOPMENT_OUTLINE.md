# 开发大纲

修改代码前先读取 [启动与开发规范](./STARTUP_GUIDE.md)，所有运行和验证均通过 Docker Compose。

## 任务路由

| 任务 | 文档 | 主要代码 |
| --- | --- | --- |
| 产品目标、文档格式和全文检索 | [业务功能说明](./BUSINESS_FEATURES.md) | `services/document_tree.py`、`services/document_search.py` |
| 工作空间/项目只读页面、AI/运维 API 和缓存链路 | [业务功能说明](./BUSINESS_FEATURES.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `workspace-dashboard.tsx`、`workspace-detail.tsx`、`middleware/browser_read_only.py`、`api/workspaces.py`、`services/project_registry.py` |
| 工作空间本机路径、卡片显示和共享文档目录 | [业务功能说明](./BUSINESS_FEATURES.md)、[启动与开发规范](./STARTUP_GUIDE.md) | `.context-router/workspaces.local.yaml`、`services/local_workspace_mapping.py` |
| 系统 JSON 文档、prepare 使用说明和系统文档菜单 | [系统文档维护说明](./SYSTEM_GUIDES.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `system-guide-manager.tsx`、`api/system_guides.py`、`services/system_guides.py` |
| 启动、测试、lint、build | [启动与开发规范](./STARTUP_GUIDE.md) | `docker-compose.yml` |
| 工作空间/项目持久化和数据库相关判断 | [数据库信息](./DATABASE_INFO.md) | `workspace_repository.py`、`project_repository.py`、`migrations/` |
| 数据库 MCP 授权和 SQL 安全 | [业务功能说明](./BUSINESS_FEATURES.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/database_access.py`、`database/policy.py` |
| Connector 或 ClickHouse 集成 | [启动与开发规范](./STARTUP_GUIDE.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `database/connectors/`、`tests/test_clickhouse_integration.py` |
| Workspace 启动、增量更新和 Host Runner | [启动与开发规范](./STARTUP_GUIDE.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/workspace_runtime_orchestration.py`、`api/runtime_runner.py`、`scripts/context_router_host_runner.py` |

## 当前架构约束

- Workspace 和 Project 的根入口文件必须命名为 `AGENTS.md`；Workspace 根入口可选，缺失时使用合成根。新 Project 的入口统一配置在 Workspace 的 `docs/` 层级下。
- 文档层级只来自 `## 下级文档` 下的“功能说明 / 相对路径”表格。存在真实 Workspace 根 `AGENTS.md` 时，展示树和 prepare 文档树严格保留其显式父子关系，不自动把 Project 根入口追加为直接下级；缺少真实根时，合成根才直接列出各 Project 入口。
- 映射由普通代码完成，不调用大模型。
- Workspace 是顶层目录、Codex task 和运行时上下文边界；根目录存在 `AGENTS.md` 时作为工作空间级文档入口。Project 必须属于一个 Workspace，保存名称、`frontend/backend` 类型、源码 `relative_path` 和文档入口 `document_relative_path`。Workspace 和 Project 都没有启停状态。源码根项目使用 `.`；项目文档入口由 `workspace.root_path / document_relative_path` 推导，兼容 `agents_path` 只作为绝对路径镜像。
- 工作空间根目录必须是绝对路径；项目源码和文档入口相对路径都禁止绝对路径、`~`、反斜杠和 `..`，解析后不能通过软链接越出工作空间，同一工作空间内两类路径分别唯一。新文档入口必须位于 `docs/` 下并以 `AGENTS.md` 结尾。
- 工作空间业务 ID、项目和数据源配置保存在 PostgreSQL；卡片显示、主目录和共享文档目录由当前项目 `.context-router/workspaces.local.yaml` 控制。启用本机文件后，不使用数据库 `root_path` 覆盖本机路径。
- 主目录是文档和部署文件的唯一维护目录。`document_reader_paths` 中相同代码的其他分支目录可 prepare/search/read 主目录文档，但数据库和部署工具必须拒绝。
- `workspace_shared_files` 保存主目录文档和部署文件的数据库副本。页面只提供双向全量覆盖，不维护版本、差异或冲突状态。
- Context Router 自身的使用规则保存在 `system_guides`，不写入业务工作空间；页面另外直接展示当前 MCP `tools/list`，prepare 不返回系统文档。
- 浏览器管理面以只读查看为主，并允许既有安全操作以及已有系统文档 JSON 正文的受校验保存。系统文档的新建、删除和元数据调整只供本机 AI/运维；页面只有“保存内容”。
- 工作空间、项目、数据源、数据库清单、项目授权、环境映射/JSON、默认环境和运行配置仍由本机 AI/运维使用既有受校验 API 维护；此类调用不携带 `Origin` 或 `Sec-Fetch-*` 浏览器请求头。不要为了绕过页面限制直接写 PostgreSQL，否则会跳过路径、事务、环境 revision、缓存与 Connector 失效处理。
- 物理数据源配置全局共享，数据库授权继续由 `project_databases` 绑定具体 Project；Workspace task 汇总使用所有子项目当前有效的授权，`mcp_alias` 在整个 Workspace 内大小写无关唯一。
- 可选的 Workspace 数据库环境映射把同一逻辑别名分别绑定到 TEST/UAT 的项目数据库关联。`prepare_task_context` 可选传 `environment='test'|'uat'`：显式值只固定本 task 的 `task_explicit` 环境，不修改 Workspace 当前环境；省略时固化当前环境并记录为 `workspace_default`。两种模式都保存共享 revision，revision 变化后旧 task 必须重新 prepare，禁止静默换库。
- 没有配置环境选择器的单环境 Workspace 继续使用原有 Workspace alias 链路；省略 `environment` 保持旧行为，显式传入时返回 `environment_not_configured`，不得猜测或自动创建选择器。
- 同一 Workspace 环境选择器还可分别保存 TEST/UAT JSON 对象，用于 MQ、Redis、MinIO、ES、任务调度或未来组件的环境差异；JSON 不预设字段，也不要求数据库映射存在。可按明确业务需要保存地址和访问凭据，但内容以明文 JSONB 保存在本地，所选环境 JSON 只在显式调用 `read_task_context` 时返回给可信本机 MCP 调用方，严禁进入日志、开发文档、链路摘要或示例输出。两份 JSON 合计最多 256 KiB、最多嵌套 20 层。
- Workspace 还可按 `default/test/uat` 保存 Nacos 配置档和组件抽取规则。prepare 未显式传环境时，`read_middleware_context` 固定读取 `default/local`；显式传 `test/uat` 时读取同名配置档，不受 Workspace 当前默认环境影响。工具只接受 task_id、可选组件名和明文开关；规则以 JSON 定义 dataId、group 和字段路径，新增中间件无需修改 Python。本机工具默认返回明文，显式 `reveal_secrets=false` 时脱敏，响应值永不写入 Trace 摘要或 payload 表。
- 完整 Workspace prepare 的 `access` 包含 `middleware`。工具说明明确允许在本机授权任务的当前回答和连接诊断中返回、使用明文凭据，同时禁止将实际值写入源码、Markdown、持久化日志、无关工具参数或提交记录；`read_task_context` 的通用环境 JSON 不作为 Nacos 中间件实时信息的权威来源。
- 刷新以 Workspace 为单位全量重建可选根入口和全部子项目并统一替换；会遍历并记录全部失败项目，任一入口文档构建失败时仍保留上一版工作空间映射。
- 前端只从 Workspace 树接口获取显式根树或合成根树，从 Workspace 文档详情接口按需获取内存正文；未出现在真实根显式树中的 Project 文档仍保留在 Workspace 搜索和按 ID 读取范围。
- Workspace 根通过 Docker 可写挂载，仅供显式“从数据库恢复”全量覆盖；普通文档读取和扫描不写目标目录。
- MCP `tools/list` 固定为七个上下文/数据库/中间件工具和三个 Workspace 运行编排工具，不按项目、数据源或中间件动态注册工具。
- Workspace 是运行编排边界：`start_workspace` 始终执行 Workspace 完整启动，`apply_workspace_changes` 按一次提交的全部改动选择项目 fast/full 或 Workspace full，`get_workspace_operation` 只查询异步状态。目标根 `.env.local` 是机器差异的唯一入口，不进入 Git、控制面数据库、执行快照或日志。
- Context Router 只做运行控制面和快照物化；手动启动的 Host Runtime Runner 通过回环 Token 协议领取租约并执行固定 `deploy.sh`。禁止配置 Docker/launchd 开机自启，禁止从后端容器直接执行目标 Workspace。
- 新 task 的文档搜索固定绑定 Workspace，查询工作空间根文档独立索引及各 Project 同版本索引，再聚合去重；索引不可用时显式失败，不回退到进程内全文扫描。
- cwd 路由先按最长前缀选择最深 Workspace，再按 Project 的源码根而不是文档入口目录选择最深 Project；`active_project` 只作为元数据，不收窄 Workspace 的文档和数据库范围。任一项目缓存不可用时 prepare 明确失败。
- prepare 只返回 task_id、可用能力、必要 warning，以及节点仅含 `document_id/summary/children` 的任务局部三层投影：存在真实 Workspace 根 `AGENTS.md` 时固定以它为第一层；缺少真实根时，才以 cwd 命中的 Project 入口或合成根为第一层。数据库别名和环境 JSON 由 `read_task_context` 按需返回。投影之外的深层或其他 Project 文档继续通过 Workspace 搜索和按 ID 读取访问。数据库访问统一按 `task_id -> workspace snapshot -> workspace mcp_alias -> 当前项目授权/连接/策略 -> Connector` 路由。
- 项目数据库只有在数据库可用且非系统库、关联为只读、存在 MCP 别名、Engine 已实现 Connector 时才暴露给 Workspace task；Workspace、数据源和关联均没有启停状态。
- MySQL、MariaDB、PostgreSQL、ClickHouse 当前实现发现、对象搜索和有界只读查询；SQL Server、SQLite、Oracle 的配置仅供查看并可由 AI/运维 API 维护。
- SQL 安全策略必须 fail-closed：只允许单条、可解析、限定当前数据库/Schema 的只读语句；不能把客户端 LIMIT 当作唯一边界，仍需服务端行数、字节数、超时和数据库侧只读限制。
- Connector 延迟创建且生命周期只归 `ConnectorManager`；数据源配置版本变化或删除时必须失效旧连接，应用退出时统一关闭。
- `mcp_database_calls` 审计历史只保存客观元数据和 SQL SHA-256；两个数据库 MCP 工具另以独立、可过期的有界 JSON 快照保存实际请求和最终 MCP 响应，主 Trace 接口不内联这些大字段。
- Context Router 十个当前 MCP 工具在统一分发入口记录到 `mcp_tool_calls`；任务内顺序由 PostgreSQL 调用 ID 生成，文档/数据库专属明细通过 `tool_call_id` 关联，观测失败不得改变工具业务结果；中间件工具只记录组件数量、脱敏模式和警告数量，不记录连接值；已下线的 Project 兼容工具历史仍可查询。
- 调用链路页面记录 Codex、Antigravity 等客户端实际发送到 Context Router `/mcp` 的十个当前工具调用，并保留两个已下线 Project 工具的历史记录；不连接、代理、聚合或接收其他 MCP Server 的调用上报，也不建设跨 Server Trace。
- 顶层页面只读展示 Workspace；进入详情后使用“前端项目 / 后端项目 / 数据源汇总”三页签。环境详情、查看调用记录、查看文档树和查看 MCP JSON 位于 Workspace 工具栏；前端项目不显示数据库授权，后端项目只读展示项目级数据源授权。环境映射/JSON与运行配置同样只读。
- 完整出入参只对白名单数据库工具 `search_database_objects`、`execute_database_query` 自动采集，并通过 no-store 详情 API 懒加载；prepare/search/read 不建立完整 payload 快照。
- 新 task 使用 `scope='workspace'` 和无外键的稳定 Workspace/活动项目快照；`scope='project'` 的旧 task 继续按原 project_id/project_key 读取、搜索和解析数据库，避免升级后历史串链。后端启动会收敛遗留 running 调用，Trace API 与页面明确区分完整、运行中和可能不完整。
- migration head 为 `20260811_0028`；`0027` 增加 UI Project 运行操作，`0028` 增加 Workspace Nacos 中间件配置档。旧项目 ID、数据库授权和调用历史保持不变。
- 本地服务默认只绑定回环地址；真实 ClickHouse 测试使用根 Compose 的 `integration` profile 和固定镜像版本。
