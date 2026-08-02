# 前后端链路速查

## 总体链路

```text
Browser
  -> Next.js 工作空间卡片
  -> FastAPI 工作空间只读 API
  -> PostgreSQL workspaces
  -> 可选 workspace.root_path / AGENTS.md
  -> 工作空间详情中的项目元数据卡片
  -> PostgreSQL document_projects(workspace_id, relative_path, document_relative_path)
  -> ProjectRegistry 当前运行时缓存
  -> workspace.root_path + project.relative_path 定位源码根
  -> workspace.root_path + project.document_relative_path 定位 docs 项目入口
  -> 分别映射到容器只读工作区并校验不能越出工作空间
  -> 分别递归解析 Workspace/Project 的“下级文档”表格
  -> 真实 Workspace 根严格保留显式父子关系；缺少真实根时由合成根直接挂载 Project 入口
  -> 生成确定性文档版本并重建独立的 Workspace/Project PostgreSQL 词法搜索索引
  -> 原子替换内存树和 Markdown 原文缓存
```

```text
Browser with Origin or Fetch Metadata
  -> frontend browser-api-policy
  -> BrowserReadOnlyMiddleware
  -> 允许 GET / HEAD / OPTIONS
  -> 仅额外允许连接测试、密码 reveal、MCP integration test、prepare preview、Workspace refresh 五类 POST
  -> 其他配置写请求返回 405 management_read_only

Local AI / operations without browser headers
  -> 既有 POST / PUT / PATCH / DELETE 本地 API
  -> Schema + Service + Repository 校验
  -> PostgreSQL / ProjectRegistry / ConnectorManager
```

这条分流用于回环单用户部署中的界面/命令职责隔离，不是身份认证方案。配置维护应优先使用既有受校验本地 API，避免直接写 PostgreSQL 而跳过路径校验、事务、环境 revision 和 Connector 失效逻辑。

```text
Codex / Antigravity
  -> POST /mcp
  -> prepare_task_context
  -> ContextPreparationService
  -> ProjectRegistry 按 cwd 最长前缀选择最深 Workspace
  -> 在 Workspace 内按源码根选择最深 Project 作为 active_project 元数据
  -> 检查 Workspace 开关和全部项目缓存
  -> PostgreSQL mcp_tasks 生成 scope=workspace 的 task_id
  -> 保存稳定 workspace 与可选 active_project 快照
  -> 返回 workspace + projects + active_project + 显式根树或合成根树 JSON
  -> read_context_document(task_id, requests[])
  -> ContextDocumentReadService 按稳定 workspace_id/workspace_key 校验任务
  -> Workspace DocumentCache 按请求顺序返回完整 Markdown 或章节
  -> PostgreSQL 生成 read_call_id 并保存 position/status
```

cwd 匹配先决定 Workspace 边界，再按 Project 源码 `relative_path` 选择最深活动项目；docs 文档入口目录不参与源码归属。最深 Project 仅作为“当前主要开发位置”的快照返回，不会把文档和数据库范围收窄到该项目。Workspace 和 Project 都没有启停状态；任一子项目映射不可用时，新的 Workspace prepare 会明确失败。

```text
Codex / Antigravity
  -> prepare_task_context 返回 task_id、文档导航树和全部 Project 元数据
  -> search_context_documents(task_id, query, limit)
  -> ContextDocumentSearchService 按 task 的稳定 Workspace 快照解析全部项目
  -> 校验 Workspace 根索引及各 Project index_version == DocumentCache.version
  -> PostgreSQL simple 全文检索 + pg_trgm + 精确子串匹配
  -> 嵌套重复文档归最深 Project，结果按 Workspace 相对路径聚合排序
  -> 按文档聚合并返回 title/summary/匹配章节/相关度/命中原因
  -> read_context_document(task_id, 命中的 document_id/section)
```

搜索只在 task 绑定 Workspace 内执行，不返回完整正文。真实根未显式挂载的 Project 文档不会出现在导航树中，但仍由 Project 索引命中并可按搜索结果 ID 读取。`workspace_document_search_chunks` 保存可选 Workspace 根文档的派生分块，`document_search_chunks` 继续按 Project 保存；磁盘 Markdown 是唯一原文真源。任一参与入口的索引缺失、构建失败或版本不一致时显式返回 index-not-ready，不回退到内存全文扫描。旧 `scope=project` task 继续只搜索原项目。

```text
Codex / Antigravity
  -> prepare_task_context(..., environment?='test'|'uat')
  -> 有选择器：显式参数记录 task_explicit；省略参数记录 workspace_default
  -> 显式参数不修改 Workspace 当前环境
  -> 无选择器：省略参数保持旧链路；显式参数返回 environment_not_configured
  -> 返回 task_id + 可选 database_environment/selection/revision + databases[].database(mcp_alias)
  -> search_database_objects / execute_database_query
  -> DatabaseAccessService 读取 task_id 绑定的稳定 workspace_id/workspace_key
  -> ProjectRegistry 校验当前 Workspace
  -> 未配置环境映射时按 workspace_id + mcp_alias 读取原项目授权
  -> 配置环境映射时先校验共享 revision，再按 task 环境和稳定 mcp_alias 解析目标授权
  -> ConnectorRegistry 校验 Engine 能力
  -> SQL/对象范围策略与全局硬上限
  -> ConnectorManager 延迟创建或复用有界连接
  -> MySQL / MariaDB / PostgreSQL / ClickHouse Connector
  -> DatabaseResultFormatter 按对象数、行数和字节数格式化/截断
  -> PostgreSQL mcp_database_calls 保存客观调用元数据
```

数据库授权记录仍属于具体 Project，但 `mcp_alias` 在 Workspace 内大小写无关唯一。未配置环境选择器时，省略 prepare 的 `environment` 保持原有解析，显式传参返回 `environment_not_configured`。配置选择器后，逻辑映射分别指向 TEST/UAT 的既有项目授权：`task_explicit` 使用显式任务环境且不修改 Workspace 当前环境，`workspace_default` 使用 prepare 当时的当前环境；两者都把环境、选择模式和共享 revision 写入 task。保存映射、保存环境 JSON 或切换当前环境引起 revision 变化后，旧 task 再调用数据库工具时返回 `environment_changed`，避免静默换库。旧 `scope=project` task 保持原项目授权范围。

```text
Codex / Antigravity
  -> prepare_task_context 返回 task_id 和 Workspace 边界
  -> 修改完成：apply_workspace_changes(task_id, changed_files)
     或明确启动：start_workspace(task_id)
  -> WorkspaceRuntimeOrchestrationService 校验 task 与相对路径
  -> 最长 Project 前缀、Workspace 路径和运行策略选择 fast / full / workspace start
  -> RuntimeMaterializationService 写入不可变 Manifest、文件哈希和 deploy.sh 快照
  -> PostgreSQL runtime_operations + runtime_operation_steps 排队
  -> 手动启动的 Host Runtime Runner 注册、心跳并领取租约
  -> 校验 loopback、Token、Manifest、哈希、Workspace 根、Project 根和软链接边界
  -> 在目标 Workspace 根执行快照 deploy.sh，目标脚本自行读取 .env.local
  -> 按顺序回报步骤；首个失败后其余步骤 skipped；不自动修复或清理
  -> get_workspace_operation(operation_id) 轮询 queued / running / succeeded / failed
```

`start_workspace` 不接收 Project 参数，任何“启动”语义都执行 Workspace 完整启动。`apply_workspace_changes` 一次接收本轮全部改动路径；跨项目、Workspace 级路径、`.env.local` 或无法唯一归属时选择完整更新。`.env.local` 只存在目标机器磁盘，不进入控制面数据库和快照。Context Router 负责决策与状态，Host Runner 负责宿主机执行，目标仓库脚本负责 Docker 和依赖配置。

```text
Codex / Antigravity
  -> POST /mcp tools/call
  -> ContextRouterMCP 统一采集工具名、task_id、开始时间和脱敏参数摘要
  -> PostgreSQL mcp_tool_calls 生成 tool_call_id
  -> ContextVar 把 tool_call_id 传给文档读取或数据库调用明细
  -> 工具完成后更新状态、结束时间、耗时、结果摘要或稳定错误码
  -> 仅数据库工具自动把有界请求和最终 MCP 响应写入独立、可过期 payload 表
  -> GET /api/mcp-traces[/{task_id}]
  -> 调用链路页面按服务端 sequence 展示调用树和调用列表
  -> 点击数据库调用后才 GET /api/mcp-traces/{task_id}/calls/{tool_call_id}/database-payload
```

`mcp_tool_calls.id` 由 PostgreSQL Identity 生成，任务内展示顺序由后端按该 ID 计算，不依赖客户端 sequence、前端时间戳拼接或任务锁。旧文档/数据库调用由 migration 恢复为 `legacy` 节点，因此升级后仍可查看历史记录。后端启动时会把上次进程遗留的内部 `running` 调用收敛为 `error/server_restarted`，避免页面永久显示运行中。

这条链路的边界固定在 Context Router 自身：只有进入 `/mcp` 并由 `ContextRouterMCP` 分发的十个内部工具会被记录。客户端对 GitHub、浏览器或其他 MCP Server 的直连请求不会经过本服务，也不会通过客户端上报补录；链路页面不尝试呈现跨 Server 调用。

prepare 和文档搜索不建立业务数据库连接。业务数据库离线时，`/health`、文档 prepare/search/read 仍可工作；MCP 链路只有实际对象搜索或查询会尝试连接，浏览器连接测试以及 AI/运维触发的数据库同步才会显式连接。

物理数据源和数据库清单是全局配置，项目授权仍由 `project_databases` 独立持久化。工作空间详情的“数据源汇总”只读取该工作空间所有项目的授权并按物理数据源和数据库去重，不创建第二套 Workspace 授权，也不改变项目的查询策略；`project_databases.workspace_id` 负责 Workspace alias 唯一性和聚合查询。

## 页面到 API

| 页面行为 | 前端 | 后端 API |
| --- | --- | --- |
| 加载工作空间卡片 | `workspace-dashboard.tsx` | `GET /api/workspaces` |
| 刷新工作空间映射 | `workspace-dashboard.tsx` | 安全 `POST /api/workspaces/{id}/refresh` |
| 按工作空间类型切换卡片 | `workspace-dashboard.tsx` | 复用 `GET /api/workspaces` 返回的 `workspace_type` 在前端筛选 |
| 加载工作空间内项目卡片 | `workspace-detail.tsx`、`project-dashboard.tsx` | `GET /api/workspaces/{id}/projects` |
| 按前端/后端类型切换项目卡片 | `workspace-detail.tsx`、`project-dashboard.tsx` | 复用项目列表中的 `project_kind` 在前端筛选 |
| 打开工作空间全屏树 | `workspace-detail.tsx`、`document-tree.tsx` | `GET /api/workspaces/{id}/tree` |
| 点击工作空间树节点查看详情 | `markdown-viewer.tsx` | `GET /api/workspaces/{id}/documents/{document_id}` |
| 查看工作空间 MCP JSON | `workspace-detail.tsx`、`project-dashboard.tsx` | 安全 `POST /api/workspaces/{id}/prepare-preview` |
| 查看工作空间调用记录 | `workspace-detail.tsx`、`project-dashboard.tsx`、`task-history.ts` | `GET /api/workspaces/{id}/tasks`、`GET /api/tasks/{task_id}/document-reads` |
| 查看工作空间数据源汇总 | `workspace-data-source-overview.tsx` | `GET /api/workspaces/{id}/data-source-summary` |
| 查看项目数据库环境映射 | `workspace-environment-mapping.tsx` | `GET /api/workspaces/{id}/database-environment-mappings` |
| 查看 TEST/UAT 通用环境 JSON | `workspace-environment-mapping.tsx` | `GET /api/workspaces/{id}/environment-config` |
| 按数据源分类切换卡片 | `data-source-dashboard.tsx` | 复用 `GET /api/data-sources` 返回的 `category` 在前端筛选 |
| 加载连接和数据库清单 | `data-source-dashboard.tsx` | `GET /api/data-sources`、`GET /api/data-sources/{id}/databases` |
| 按需查看数据源密码 | `data-source-dashboard.tsx` | 安全 `POST /api/data-sources/{id}/reveal-password`，响应禁止缓存 |
| 加载 Engine 能力矩阵 | `data-source-dashboard.tsx` | `GET /api/data-source-engines` |
| 测试当前连接 | `data-source-dashboard.tsx` | 安全 `POST /api/data-sources/{id}/test`，返回状态、耗时和短错误码 |
| 查看全局 MCP 链路 | `trace-explorer.tsx`、`mcp-traces.ts` | `GET /api/mcp-traces`、`GET /api/mcp-traces/{task_id}` |
| 查看后端项目数据源授权 | `project-dashboard.tsx` | `GET /api/projects/{id}/data-source-options` |
| 查看项目运行配置 | `project-runtime-config.tsx` | `GET /api/projects/{id}/runtime-config` |
| 查看运行记录与有界日志 | `project-runtime-config.tsx` | `GET /api/projects/{id}/runtime-runs`、`GET /api/projects/{id}/runtime-runs/{run_id}`、`GET /api/projects/{id}/runtime-runs/{run_id}/log` |
| 查看 Workspace 运行配置 | 暂无浏览器写入口 | `GET /api/workspaces/{id}/runtime-config` |
| 配置 Workspace 启动文件与策略 | 本机 AI / 运维 | `PUT /api/workspaces/{id}/runtime-config/start`、`PUT /api/workspaces/{id}/runtime-policy` |
| 查看 Workspace 运行操作 | 暂无独立页面 | `GET /api/workspaces/{id}/runtime-operations`、`GET /api/workspaces/{id}/runtime-operations/{operation_id}` |
| 打开当前工作空间 MCP 接入面板 | `workspace-detail.tsx`、`mcp-integration-panel.tsx` | `GET /api/mcp/integration` |
| 对当前工作空间执行 MCP 连接测试 | `mcp-integration-panel.tsx` | 安全 `POST /api/mcp/integration/tests`，请求体使用 `workspace_id` |

浏览器不调用工作空间、项目、数据源、数据库清单、项目授权、环境映射/JSON、当前环境或运行配置的配置写 API，也不触发数据库同步、运行配置物化或执行；仅额外允许 Workspace 刷新重建可恢复的文档缓存和派生搜索索引。其余 `POST/PUT/PATCH/DELETE` contract 保留给不携带 `Origin` 或 `Sec-Fetch-*` 浏览器请求头的本机 AI/运维调用方，后端继续执行原有业务校验与副作用管理。

## 后端代码

```text
api/workspaces.py
  -> services/workspace_management.py
  -> repositories/workspace_repository.py
  -> services/project_registry.py
  -> services/document_tree.py
  -> repositories/project_repository.py
  -> schemas/workspaces.py / schemas/projects.py
```

- `BrowserReadOnlyMiddleware` 根据任意 `Origin` 或浏览器 Fetch Metadata 拦截配置写请求；`frontend/lib/browser-api-policy.ts` 在请求发出前执行同一只读策略。双层限制共享 `GET/HEAD/OPTIONS` 与五类安全 `POST` 边界，Workspace refresh 只重建文档缓存和派生搜索索引。
- `WorkspaceManagementService` 继续为本机 AI/运维编排受校验的工作空间 CRUD、工作空间内项目 CRUD、刷新和数据源汇总；`workspace_repository.py` 持久化工作空间根目录、类型和总开关。
- `project_repository.py` 持久化稳定项目 ID、`workspace_id`、`frontend/backend` 的 `project_kind`、工作空间内分别唯一的源码 `relative_path`、文档入口 `document_relative_path` 和兼容字段；`document_projects` 不再有 enabled。后端启动时从独立文档入口重建缓存，路径失效项目保留配置和错误。
- `ProjectRegistry` 管理可选的 Workspace 根文档缓存和每个 Project 缓存；根 `AGENTS.md` 存在时，导航树严格采用其显式父子关系，未声明的 Project 根不自动挂入树中；根入口不存在时动态构建直接列出 Project 的合成入口。两种情况下 Workspace 聚合缓存都保留全部项目文档，供搜索和按 ID 读取。cwd 先按根目录深度选择最深 Workspace，再按源码根选择最深 Project 作为 `active_project`。
- 工作空间类型用于管理页面分类，并作为所属项目的兼容 `project_type`；Project 的业务类型只允许 `frontend/backend`。数据源分类由 `data_sources.category` 独立持久化，不复用工作空间类型。
- 数据源列表始终过滤口令；只有只读连接详情的眼睛按钮调用独立接口读取明文密码。连接测试使用临时 Connector，完成后关闭，不进入长期缓存，也不向响应暴露连接配置。
- MySQL/MariaDB/PostgreSQL/ClickHouse 自动同步由 `database_discovery.py` 使用对应驱动读取远端数据库清单，保留已有记录 ID 和项目关联，新增可见库并把本次未发现的旧库标记为不可用。同步只由 AI/运维 API 触发，失败不会替换现有数据库清单。
- 项目侧数据源选项接口按数据源分组返回数据库清单且不返回连接口令；浏览器只展示现有选择。本机 AI/运维批量保存时使用单个数据库事务替换该项目关联，保留仍被选中的既有策略，新关联使用默认只读限制。`mcp_alias` 虽保存在项目关联上，但更新接口、Repository 和数据库唯一索引都按 Workspace 校验。
- `database_environments.py`、`DatabaseEnvironmentRepository` 和环境 Schema 负责 Workspace TEST/UAT 选择器、数据库映射及通用 JSON 对象。数据库建议匹配只按名称去掉 `test_`/`uat_` 后的同后缀生成，最终保存仍校验目标属于同一 Workspace 和 Project 的既有授权；通用 JSON 不预设字段且不要求数据库映射存在，大小、深度和数字范围由后端限制。浏览器只读；AI/运维触发的三类写操作都在单个事务内递增共享 revision。
- 工作空间根目录必须是绝对目录；项目源码和文档入口相对路径禁止绝对路径、`~`、反斜杠和 `..`，并通过真实路径校验阻止软链接越界。新文档入口必须位于 `docs/` 下并以 `AGENTS.md` 结尾。AI/运维新增、编辑和删除项目时先完成必要的磁盘验证与数据库写入，再原子更新注册表；数据库写入失败时不改变当前内存项目。
- 工作空间、数据源和项目数据库授权都没有启停开关；记录存在即参与相应的目录匹配、汇总与访问校验。
- `build_document_cache` 负责递归读取、路径校验、循环检测和正文缓存。
- Workspace 刷新先构建可选根入口并遍历全部子项目生成新的 `DocumentCache`，把所有失败入口写回对应项目后统一返回问题；任一构建失败时保留全部旧缓存。全部构建成功后再统一替换，并生成显式根树或合成根树，同时把全部项目文档合并到 Workspace 搜索和读取范围。
- `document_metadata.py` 在刷新时安全解析显式 title 和 summary。
- `markdown_search_parser.py` 剥离 Front Matter、按 fenced-code-aware ATX 章节解析并生成有界、带重叠的规范化分块。
- `document_search_repository.py` 使用 PostgreSQL `simple` FTS、`pg_trgm` 和短词精确子串查询 Workspace 或 Project 的当前索引版本；两类索引分别持久化，避免使用伪 Project。
- `ContextDocumentSearchService` 按 task scope 选择 Workspace 或旧 Project 兼容链路，校验 Workspace 根入口和各项目 index_version，将分块命中聚合为文档结果；只返回定位信息，不返回 Markdown 正文。
- `ContextPreparationService` 为 MCP 和本机 Workspace MCP JSON 预览生成包含显式根树或合成根树、全部项目、活动项目、可选任务数据库环境和全 Workspace 可用数据库摘要的同一返回模型，不 ping 远端数据库。调用方可选传 `environment='test'|'uat'`；显式选择不会调用 Workspace 切换接口。通用 JSON 是用户显式维护内容，不自动读取 Nacos 或数据源连接配置；task 所选环境的 `environment_config` 会返回给可信本机 MCP 调用方和本机预览，但不进入日志、开发文档或链路摘要。
- `task_repository.py` 为新 prepare 写入 `scope='workspace'`、Workspace 快照、可选活动项目快照、环境、共享 revision 和 `database_environment_selection`。`20260730_0021` 把已有非空环境 task 回填为 `workspace_default`；显式新任务写 `task_explicit`。migration 前的记录保留 `scope='project'`，同时回填 Workspace 字段以便在工作空间调用记录中查询；read/search 仍走原 Project 兼容路径，但 Workspace 启用环境选择器后，旧 Project task 的数据库调用必须重新 prepare。
- `ContextDocumentReadService` 按 task scope 校验 Workspace 聚合缓存或旧 Project 缓存，批量读取文档或章节，并在返回正文前记录调用。
- `document_read_repository.py` 保存 read_call_id、单次 position、相对路径、章节和状态，不保存正文。
- `DatabaseAccessService` 是数据库调用的授权入口。`workspace_default` 同时校验 task 环境仍等于 Workspace 当前环境且共享 revision 一致；`task_explicit` 不要求等于当前环境，但仍要求选择器存在且 revision 一致。只配置通用 JSON 时校验后继续原有 Workspace alias 链；存在数据库映射记录时，再按 task 环境由稳定 alias 解析目标。没有选择器且 task 没有环境快照时继续旧链路；显式环境缺少选择器则失败关闭。环境选择器配置前的旧 `scope=project` task 必须重新 prepare，防止绕过 revision。所有链路都不接受 Host、DSN、账号或远端库名。
- `database/policy.py` 使用 SQLGlot fail-closed 校验单条只读 SQL，拒绝写入、多语句、跨数据库、外部表函数、文件/网络读取和调用方自带 SETTINGS。
- `DatabaseCatalogService` 提供 schema/table/view/column/index 的 `names`、`summary`、`full` 渐进搜索；细节越高，允许返回的对象数越少。
- `DatabaseQueryService` 执行有界只读查询；`DatabaseResultFormatter` 统一处理复杂类型、结果大小和明确截断元数据。
- `ConnectorManager` 以数据源配置版本和数据库更新时间组成缓存键，提供延迟连接、同 key single-flight、并发限制、LRU 淘汰和失效关闭。
- `database_call_repository.py` 记录 operation、数据库别名/Engine 快照、对象或语句类型、SQL SHA-256、状态、耗时、数量、字节数、截断和稳定错误码；不保存完整 SQL 或结果。
- `database_tool_payload.py` 与独立 Repository 只对白名单数据库工具自动保存有界请求和最终 MCP 响应。请求/响应默认各 1 MB、硬上限 4 MB、默认保留 7 天；启动时恢复 pending 并清理过期内容，调用期间按节流周期继续清理。
- `workspace_runtime_orchestration.py` 以 task 的 Workspace 快照为边界，负责改动归属、fast/full/start 选择、确定性步骤顺序和操作查询；`runtime_materialization.py` 生成不可变执行快照。
- `runtime_runner.py` 暴露只允许 Bearer Token 且拒绝浏览器请求的注册、心跳、领取租约和完成回报协议；`scripts/context_router_host_runner.py` 是手动启动的宿主机执行器。
- `mcp_server.py` 固定注册五个上下文/数据库工具、三个 Workspace 运行工具和两个 Project 兼容工具，并挂载到 `/mcp`。项目或数据源变化不会改变工具名。
- `mcp_server.py` 使用统一工具分发埋点记录十个固定工具；观测持久化失败只降低链路可见性，不改变 MCP 工具原始成功或失败结果。
- `mcp_tool_call_repository.py` 保存通用工具调用和任务链路摘要；文档与数据库 Repository 继续保存各自明细，并通过可空唯一 `tool_call_id` 关联。
- `api/mcp_traces.py` 返回全局任务链路列表和单任务统一调用详情；列表支持项目、Agent、固定内部工具、调用状态和关键词的服务端过滤。普通 task 即使没有成功落下内部调用节点也能显示，`web-preview` 与 `connection-test` 系统任务除外。API 已把文档、数据库明细转换为同一 `artifacts` 数组，并返回 `complete / running / partial` 完整性状态与稳定 warning code；主详情只包含 payload 的 available/status/reason，完整 JSON 由带 `Cache-Control: no-store` 的归属校验接口懒加载。
- `mcp_integration.py` 生成客户端配置，并接收 `workspace_id`，以 MCP Python Client 对后端自身执行 initialize、tools/list、Workspace 匹配、prepare、search 和 read，不绕过协议直接调用 service。
- 接入测试只返回阶段状态、耗时、task_id、read_call_id 和正文字符数；数据库 URL 与 Markdown 正文不进入 API 响应，且该测试不执行项目业务数据库查询。

## Engine 能力矩阵

| Engine | 配置可持久化 | 浏览器连接测试 | AI/运维同步数据库 | 对象搜索 | 有界只读查询 |
| --- | --- | --- | --- | --- | --- |
| MySQL | 是 | 是 | 是 | 是 | 是 |
| MariaDB | 是 | 是 | 是 | 是 | 是 |
| PostgreSQL | 是 | 是 | 是 | 是 | 是 |
| ClickHouse | 是 | 是 | 是 | 是 | 是 |
| SQL Server | 是 | 否 | 否 | 否 | 否 |
| SQLite | 是 | 否 | 否 | 否 | 否 |
| Oracle | 是 | 否 | 否 | 否 | 否 |

前端必须以 `GET /api/data-source-engines` 的响应为真值，不通过静态 Engine 列表推断连接测试或“MCP 可查询”状态。

## 前端代码

```text
app/page.tsx
  -> components/app-shell.tsx
     -> components/workspace-dashboard.tsx
        -> components/workspace-detail.tsx
           -> components/project-dashboard.tsx
              -> components/document-tree.tsx
              -> components/markdown-viewer.tsx
              -> components/mcp-integration-panel.tsx
              -> components/workspace-environment-mapping.tsx
              -> components/project-runtime-config.tsx
           -> components/workspace-data-source-overview.tsx
     -> components/data-source-dashboard.tsx
     -> lib/api.ts
     -> lib/browser-api-policy.ts
     -> lib/markdown.ts
```

Markdown 解析器只生成 React 元素，不使用 `dangerouslySetInnerHTML`，也不执行文档里的原始 HTML。

工作空间列表只负责分类筛选、摘要展示和进入详情。详情页按“前端项目 / 后端项目 / 数据源汇总”三页签组织只读内容，项目卡片分开展示 `project_kind`、源码 `relative_path` 和 docs 文档入口 `document_relative_path`。“环境详情 / 查看调用记录 / 查看文档树 / 查看 MCP JSON”位于 Workspace 工具栏；环境详情以页签只读展示数据库稳定别名及 TEST/UAT 物理目标、两份无固定字段的 JSON 和默认环境，不提供匹配、保存或切换。“数据源汇总”只做聚合展示。

数据源卡片进入“查看连接”详情，保留分类筛选、连接参数和数据库清单查看、密码按需 reveal 与连接测试；工作空间的后端项目只读展示当前数据库授权。运行配置页只读展示快速/完整部署文件、历史运行状态和日志，不调用配置保存、物化或执行 API。

Workspace 调用记录通过 `task-history.ts` 保留文档读取批次和单批位置，通过 `database-access.ts` 把文档 read call 与数据库 call 按创建时间合并为上下文时间线。历史“文档树”视图在前端以被调用文档 ID 为集合递归裁剪当前 Workspace 文档树，只保留命中节点及其全部祖先，隐藏无关旁支和命中节点下未调用的后代；正常“查看文档树”仍展示完整树。后端工作空间任务列表在 `LIMIT` 前过滤既没有 read call 也没有数据库调用的任务；同一次批量读取的文档在一行横向展示，读取成功的卡片复用 Workspace 文档详情接口和 Markdown 抽屉。数据库卡片仍只展示客观摘要。

全局调用链路页由 `trace-explorer.tsx` 读取统一 Trace API，服务端直接返回 `sequence`、调用状态、完整性和关联 artifacts。页面提供任务、Agent、十个固定内部工具和状态筛选，只保留调用树与调用列表；“调用树”只对显式 `parent_tool_call_id` 绘制父子含义，普通调用按稳定顺序纵向排列。文档搜索节点只展示返回文档数量等脱敏摘要，文档工具不请求文档树或 Markdown；数据库工具通过 `database-call-payload-modal.tsx` 点击后懒加载全屏出入参详情。列表和详情会把链路标记为“完整 / 运行中 / 可能不完整”，并把 prepare 缺失、历史、重启中断或未关联明细转换为中文提示。

ClickHouse 连接详情展示 secure、verify、bootstrap database、connect timeout 和 send/receive timeout；项目数据源详情展示 `mcp_alias` 和只读策略。AI/运维通过既有批量 API 维护时，后端仍校验同 Workspace 其他项目的别名占用，因此支持合法的别名互换且不会部分保存。历史非只读关联会明确提示不暴露给 MCP。

MCP 接入信息和测试结果通过 `lib/api.ts` 获取；公开 MCP URL 由后端配置统一提供，前端不按浏览器地址猜测。面板展示十个固定工具，并说明文档搜索绑定 prepare 创建的 Workspace task，真正可用的数据库以 prepare 的 `databases` 为准。测试请求发送当前 `workspace_id`；端到端测试任务的 `agent_name` 固定为 `connection-test`，任务列表默认过滤这类记录。
