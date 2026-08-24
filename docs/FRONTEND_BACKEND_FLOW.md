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
  -> 额外允许既有安全 POST 与系统文档正文 PUT
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
  -> 在 Workspace 内按源码根选择最深 Project 作为 active_project
  -> 检查 Workspace 开关和全部项目缓存
  -> PostgreSQL mcp_tasks 生成 scope=workspace 的 task_id
  -> 保存稳定 workspace 与可选 active_project 快照
  -> 真实 Workspace 根存在时固定以它为第一层
  -> 缺少真实根时才从 active_project 入口或合成根开始
  -> 只投影入口及显式下两级（总高度三层）
  -> 返回 task_id + access + 三层文档投影 + 必要 warnings
  -> read_task_context(task_id, sections[])
  -> 按需返回 Workspace 数据库别名或 task 所选环境 JSON
  -> read_middleware_context(task_id, environment?, components?, reveal_secrets?)
  -> 显式 environment 优先；省略时继承 task 环境
  -> 拉取规则声明的 dataId/group，解析并抽取组件字段
  -> 本机默认明文；显式 reveal=false 时脱敏，Trace 不保存响应值
  -> read_context_document(task_id, requests[])
  -> ContextDocumentReadService 按稳定 workspace_id/workspace_key 校验任务
  -> Workspace DocumentCache 按请求顺序返回完整 Markdown 或章节
  -> PostgreSQL 生成 read_call_id 并保存 position/status
```

cwd 匹配先决定 Workspace 边界，再按 Project 源码 `relative_path` 选择最深活动项目；docs 文档入口目录不参与源码归属。真实 Workspace 根存在时，活动 Project 只保存为任务快照，不改变 prepare 根入口；缺少真实根时才用于选择 Project 入口。两种情况都不会把 search、read 和数据库权限范围收窄到该项目。Workspace 和 Project 都没有启停状态；任一子项目映射不可用时，新的 Workspace prepare 会明确失败。

```text
Codex / Antigravity
  -> prepare_task_context 返回 task_id 和根入口三层文档投影
  -> search_context_documents(task_id, query, limit)
  -> ContextDocumentSearchService 按 task 的稳定 Workspace 快照解析全部项目
  -> 校验 Workspace 根索引及各 Project index_version == DocumentCache.version
  -> PostgreSQL simple 全文检索 + pg_trgm + 精确子串匹配
  -> 嵌套重复文档归最深 Project，结果按 Workspace 相对路径聚合排序
  -> 按文档聚合并返回 title/summary/匹配章节/相关度/命中原因
  -> read_context_document(task_id, 命中的 document_id/section)
```

搜索只在 task 绑定 Workspace 内执行，不返回完整正文。未进入三层投影的深层文档、其他 Project 文档以及真实根未显式挂载的 Project 文档，仍由 Project 索引命中并可按搜索结果 ID 读取。`workspace_document_search_chunks` 保存可选 Workspace 根文档的派生分块，`document_search_chunks` 继续按 Project 保存；磁盘 Markdown 是唯一原文真源。任一参与入口的索引缺失、构建失败或版本不一致时显式返回 index-not-ready，不回退到内存全文扫描。旧 `scope=project` task 继续只搜索原项目。

```text
Codex / Antigravity
  -> prepare_task_context(..., environment?)
  -> 校验 environment 属于当前 Workspace 动态环境列表
  -> 显式参数记录 task_explicit；省略时固定 local 并记录 workspace_default
  -> 环境选择只写 task 快照，不修改 Workspace 配置
  -> 返回 task_id + 可选 database_environment/selection/revision + databases[].database(mcp_alias)
  -> search_database_objects / execute_database_query
  -> DatabaseAccessService 读取 task_id 绑定的稳定 workspace_id/workspace_key
  -> ProjectRegistry 校验当前 Workspace
  -> 校验共享 revision，再按 task 环境和稳定 mcp_alias 解析既有项目授权
  -> ConnectorRegistry 校验 Engine 能力
  -> SQL/对象范围策略与全局硬上限
  -> ConnectorManager 延迟创建或复用有界连接
  -> MySQL / MariaDB / PostgreSQL / ClickHouse Connector
  -> DatabaseResultFormatter 按对象数、行数和字节数格式化/截断
  -> PostgreSQL mcp_database_calls 保存客观调用元数据
```

数据库授权记录仍属于具体 Project，但 `mcp_alias` 在 Workspace 内大小写无关唯一。每个 Workspace 至少登记 `local`，也可以登记任意合规环境；逻辑映射把环境与既有项目授权关联，数据库本身不带环境语义，多个环境可以复用同一授权。关联 revision 变化后，旧 task 再调用数据库工具时返回 `environment_changed`，避免静默换库。

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

接口转发 MCP 的执行也优先使用具备 `interface-forwarding` 能力的在线 Host Runner：控制面先完成计划、只读分类、配置指纹和单次使用校验，再创建短租约任务；Runner 只执行服务端组装的 HTTP(S) GET/POST 请求并回传有界结果。账号请求头不落任务表、不进入 MCP 响应；Runner 不可用时保留容器内直连兼容路径。c12-data 的原始 Controller 路径不直接开放，只有登记为 MTP 可调用接口的明确包装路径才能执行。

`prepare_forwarding_request` 先解析转发配置。显式 `address_id`、`login_account`、`role_name` 优先；省略时在当前接口、task 环境和仍存在的候选中选择最近成功日志的地址与身份；没有成功记录但仅有一个候选时自动选择；其余情况返回 `needs_selection`。显式账号或角色会先排除不包含该身份的地址。`selection_evidence` 分别记录地址和身份来自 `caller`、`successful_history` 或 `single_candidate`；调用摘要只记录来源，不记录登录请求头。配置确定后，再按同接口、同环境、同转发地址、同身份选择最近一条成功日志，并在合并前移除验证码、临时令牌、时间戳等易失字段，把历史页码重置为 1、历史分页大小限制到 20。默认 `value_strategy=reuse_successful`，不会因为存在映射就查询业务数据库。用户要求更换指定业务值时使用 `refresh_selected + refresh_value_keys`；要求所有业务值重新造数时使用 `refresh_mapped`；明确拒绝历史时才使用 `ignore_history`。刷新只处理当前接口的精确参数绑定，先移除对应历史值，再从最多 10 个候选中稳定选择一个与旧值不同的值；调用方显式值最后覆盖且会跳过该字段的映射查询。返回的 `parameter_evidence` 标记 `caller`、`successful_history`、`value_mapping`、Schema 默认/示例或安全分页默认，`value_resolutions` 说明哪些映射被刷新或由 caller 覆盖；无法安全刷新时返回 `needs_value_resolution`，不生成计划。

业务值取值链路既可由 AI 显式调用 `search_value_mappings -> resolve_value_candidates`，也可由 `prepare_forwarding_request` 在刷新策略下按接口绑定自动完成。搜索工具只读取当前 task Workspace 的已发布映射，可按中文业务词、`value_key`、别名或精确的 `interface_id + location + parameter_path` 定位规则；绑定列表每条映射最多返回 20 条并标记是否截断。解析工具不接收 SQL、连接信息或任意数据源，只执行映射中保存的数据库别名、表、字段和固定等值过滤；省略环境时继承 task 环境，显式环境必须与 task 一致，结果最多 10 条并携带来源字段。两类调用均进入 MCP 链路，日志中的搜索词只保存 SHA-256 摘要；接口准备日志另外记录策略和刷新 key 数量，不记录候选原文。

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

这条链路的边界固定在 Context Router 自身：只有进入 `/mcp` 并由 `ContextRouterMCP` 分发的 22 个当前工具会被记录，三个已下线工具的既有历史继续保留。客户端对 GitHub、浏览器或其他 MCP Server 的直连请求不会经过本服务，也不会通过客户端上报补录；链路页面不尝试呈现跨 Server 调用。

prepare 和文档搜索不建立业务数据库连接。业务数据库离线时，`/health`、文档 prepare/search/read 仍可工作；MCP 链路只有实际对象搜索或查询会尝试连接，浏览器连接测试以及 AI/运维触发的数据库同步才会显式连接。

物理数据源和数据库清单是全局配置，项目授权仍由 `project_databases` 独立持久化。环境详情页的“数据源汇总”只读取所选环境关联的授权并按物理数据源和数据库去重，不创建第二套 Workspace 授权，也不改变项目查询策略。

## 页面到 API

| 页面行为 | 前端 | 后端 API |
| --- | --- | --- |
| 浏览六类共享配置并设置本机 AI 默认项 | `shared-ai-config-manager.tsx` | `GET /api/shared-config/ai/catalog` 聚合数据库、AI、本地 CLI、MinIO、图片模型和 Runtime Contract；`GET /api/shared-config/ai`、安全 `PUT /api/shared-config/ai/default` 维护本机 AI 默认项。所有明细实时取自配置中心，本地仅保存默认 Provider ID，失效时回退中心默认并返回提示 |
| 接收 AI 查询条件并查询关联数据 | `data-visualization-workbench.tsx` | Codex/Antigravity 通过 MCP `save_data_visualization_query` 按 task 保存结构化条件，本机运维也可使用 `POST /api/ai-visualization/query-records`；服务端校验 task、Workspace、环境与发布表并幂等写入。浏览器按 Workspace、环境、来源或 task 读取最近 30 天记录，查询后把状态、耗时和结果规模写回执行摘要 |
| 查看 AI 任务执行与结论 | `task-visualization-workbench.tsx` | `GET /api/ai-visualization/tasks` 聚合已有 task 的 MCP、数据、接口和日志统计，详情与时间线使用稳定游标读取；AI 通过 MCP `save_task_visualization_result` 更新同一 task 的脱敏结构化结论。浏览器只读，不创建或编辑任务 |
| 查看 AI 实际执行的接口请求 | `interface-visualization-workbench.tsx` | `GET /api/ai-visualization/interface-requests` 按 `created_at DESC, id DESC` 聚合真实接口日志、任务描述和接口摘要，支持 task 筛选和游标分页；详情通过日志 `plan_id` 返回递归脱敏的最终请求、响应和 `parameter_evidence`。页面只读，不创建第二套请求记录或调用接口 |
| 加载工作空间卡片 | `workspace-dashboard.tsx` | `GET /api/workspaces` |
| 查看并切换 Workspace 环境详情 | `workspace-mcp-environment-defaults.tsx` | `GET /api/workspaces/{id}/environments`、`GET /api/workspaces/{id}/nacos-profiles` |
| 刷新工作空间映射 | `workspace-dashboard.tsx` | 安全 `POST /api/workspaces/{id}/refresh` |
| 按工作空间类型切换卡片 | `workspace-dashboard.tsx` | 复用 `GET /api/workspaces` 返回的 `workspace_type` 在前端筛选 |
| 加载工作空间内项目卡片 | `workspace-detail.tsx`、`project-dashboard.tsx` | `GET /api/workspaces/{id}/projects` |
| 按前端/后端类型切换项目卡片 | `workspace-detail.tsx`、`project-dashboard.tsx` | 复用项目列表中的 `project_kind` 在前端筛选 |
| 打开工作空间全屏树 | `workspace-detail.tsx`、`document-tree.tsx` | `GET /api/workspaces/{id}/tree` |
| 点击工作空间树节点查看详情 | `markdown-viewer.tsx` | `GET /api/workspaces/{id}/documents/{document_id}` |
| 查看工作空间 MCP JSON | `workspace-detail.tsx`、`project-dashboard.tsx` | 安全 `POST /api/workspaces/{id}/prepare-preview` |
| 查看工作空间调用记录 | `workspace-detail.tsx`、`project-dashboard.tsx`、`task-history.ts` | `GET /api/workspaces/{id}/tasks`、`GET /api/tasks/{task_id}/document-reads` |
| 查看所选环境的数据源汇总 | `workspace-data-source-overview.tsx` | `GET /api/workspaces/{id}/data-source-summary?environment={key}` |
| 按数据源分类切换卡片 | `data-source-dashboard.tsx` | 复用 `GET /api/data-sources` 返回的 `category` 在前端筛选 |
| 加载连接和数据库清单 | `data-source-dashboard.tsx` | `GET /api/data-sources`、`GET /api/data-sources/{id}/databases` |
| 按需查看数据源密码 | `data-source-dashboard.tsx` | 安全 `POST /api/data-sources/{id}/reveal-password`，响应禁止缓存 |
| 加载 Engine 能力矩阵 | `data-source-dashboard.tsx` | `GET /api/data-source-engines` |
| 测试当前连接 | `data-source-dashboard.tsx` | 安全 `POST /api/data-sources/{id}/test`，返回状态、耗时和短错误码 |
| 加载表关联版本与表清单 | `table-relation-explorer.tsx`、`table-relations.ts` | `GET /api/workspaces/{id}/table-relations/status`、`GET /api/workspaces/{id}/table-relations/tables` |
| 查看单表关联 | `table-relation-detail.tsx`、`table-relation-edge-row.tsx` | `GET /api/workspaces/{id}/table-relations/table` |
| 按关联字段关键词查看一层关联记录 | `relation-record-explorer.tsx` | 安全只读 `POST /api/workspaces/{id}/relation-records/search` |
| 管理并测试接口转发 | `interface-forwarding-manager.tsx` | 浏览器使用 `GET /api/interface-forwarding/overview` 只读展示 Workspace 环境下“接口服务 + 具名基础 URL”映射及每个地址的登录账号、角色标识和请求头；overview 聚合接口最近请求时间，有请求记录的接口优先按时间倒序，未请求接口按路径和请求方式稳定排序；前端对当前服务或全部接口的实际展示集合复用同一排序；写入接口保留给 AI/运维调用；execute 同时校验接口与地址的服务归属，测试下拉只显示同服务地址；MCP 执行优先经 Host Runner 单次租约访问宿主机 VPN 网络并统一落日志；接口 state/logs/schema |
| 查看与使用业务值映射 | `value-mapping-manager.tsx` | 页面通过 `GET /api/value-mappings/overview` 只读展示；AI/运维接口保留结构化规则维护和预览；MCP 使用 `search_value_mappings` 定位已发布规则，再由 `resolve_value_candidates` 按 task 环境执行最多 10 条的服务端生成只读查询 |
| 查看单表插入入口 | `table-relation-write-modal.tsx` | `GET /api/workspaces/{id}/table-relations/table/writes` |
| 查看单表更新入口 | `table-relation-write-modal.tsx` | `GET /api/workspaces/{id}/table-relations/table/updates` |
| 搜索表名、只看有关联的表、折叠多对多 | `table-relation-table-list.tsx`、`table-relations.ts` | 无请求，复用已加载数据在前端过滤 |
| 写入表关联示例数据 | 无页面入口 | 无接口，执行 `context_router.scripts.seed_table_relations` |
| 查看全局 MCP 链路 | `trace-explorer.tsx`、`mcp-traces.ts` | `GET /api/mcp-traces`、`GET /api/mcp-traces/{task_id}` |
| 编辑系统 JSON 文档正文 | `system-guide-manager.tsx` | `GET /api/system-guides`、`PUT /api/system-guides/{id}/content` |
| 查看后端项目数据源授权 | `project-dashboard.tsx` | `GET /api/projects/{id}/data-source-options` |
| 查看项目运行配置 | `project-runtime-config.tsx` | `GET /api/projects/{id}/runtime-config` |
| 查看运行记录与有界日志 | `project-runtime-config.tsx` | `GET /api/projects/{id}/runtime-runs`、`GET /api/projects/{id}/runtime-runs/{run_id}`、`GET /api/projects/{id}/runtime-runs/{run_id}/log` |
| 查看 Workspace 运行配置 | 暂无浏览器写入口 | `GET /api/workspaces/{id}/runtime-config` |
| 预览仓库 deploy 配置 | `workspace-detail.tsx`、`workspace-runtime-sync.tsx` | 安全 `POST /api/workspaces/{id}/runtime-config/sync-preview` |
| 按预览摘要原子同步 deploy 配置 | `workspace-runtime-sync.tsx` | 安全 `POST /api/workspaces/{id}/runtime-config/sync` |
| 配置 Workspace 启动文件与策略 | 本机 AI / 运维 | `PUT /api/workspaces/{id}/runtime-config/start`、`PUT /api/workspaces/{id}/runtime-policy` |
| 查看 Workspace 运行操作 | 暂无独立页面 | `GET /api/workspaces/{id}/runtime-operations`、`GET /api/workspaces/{id}/runtime-operations/{operation_id}` |
| 打开当前工作空间 MCP 接入面板 | `workspace-detail.tsx`、`mcp-integration-panel.tsx` | `GET /api/mcp/integration` |
| 对当前工作空间执行 MCP 连接测试 | `mcp-integration-panel.tsx` | 安全 `POST /api/mcp/integration/tests`，请求体使用 `workspace_id` |

浏览器不调用工作空间、项目、数据源、数据库清单、项目授权、环境/Nacos/JSON 或任意运行配置写 API，也不触发数据库同步、运行配置物化或执行；仅额外允许 Workspace 刷新，以及固定目录 deploy 配置的预览和摘要确认同步。其余配置写 contract 保留给不携带浏览器识别头的本机 AI/运维调用方。

## 后端代码

```text
api/workspaces.py
  -> services/workspace_management.py
  -> repositories/workspace_repository.py
  -> services/project_registry.py
  -> services/document_tree.py
  -> repositories/project_repository.py
  -> schemas/workspaces.py / schemas/projects.py

api/table_relations.py
  -> services/table_relation_query.py
  -> repositories/table_relation_repository.py
  -> schemas/table_relations.py
```

- `BrowserReadOnlyMiddleware` 根据任意 `Origin` 或浏览器 Fetch Metadata 拦截配置写请求；`frontend/lib/browser-api-policy.ts` 在请求发出前执行同一策略。双层限制只额外开放 `PUT /api/system-guides/{id}/content`，环境与其他 Workspace 配置完整 CRUD 只供本机 AI/运维。
- `WorkspaceManagementService` 继续为本机 AI/运维编排受校验的工作空间 CRUD、工作空间内项目 CRUD、刷新和数据源汇总；`workspace_repository.py` 持久化工作空间根目录、类型和总开关。
- `project_repository.py` 持久化稳定项目 ID、`workspace_id`、`frontend/backend` 的 `project_kind`、工作空间内分别唯一的源码 `relative_path`、文档入口 `document_relative_path` 和兼容字段；`document_projects` 不再有 enabled。后端启动时从独立文档入口重建缓存，路径失效项目保留配置和错误。
- `ProjectRegistry` 管理可选的 Workspace 根文档缓存和每个 Project 缓存；根 `AGENTS.md` 存在时，完整 Workspace 树严格采用其显式父子关系，未声明的 Project 根不自动挂入树中；根入口不存在时动态构建直接列出 Project 的合成入口。两种情况下 Workspace 聚合缓存都保留全部项目文档，供搜索和按 ID 读取。cwd 先按根目录深度选择最深 Workspace，再按源码根选择最深 Project 作为 `active_project`；prepare 优先从真实 Workspace 根构建三层任务投影，缺少真实根时才回退活动 Project 或合成根。
- 工作空间类型用于管理页面分类，并作为所属项目的兼容 `project_type`；Project 的业务类型只允许 `frontend/backend`。数据源分类由 `data_sources.category` 独立持久化，不复用工作空间类型。
- 数据源列表始终过滤口令；只有只读连接详情的眼睛按钮调用独立接口读取明文密码。连接测试使用临时 Connector，完成后关闭，不进入长期缓存，也不向响应暴露连接配置。
- MySQL/MariaDB/PostgreSQL/ClickHouse 自动同步由 `database_discovery.py` 使用对应驱动读取远端数据库清单，保留已有记录 ID 和项目关联，新增可见库并把本次未发现的旧库标记为不可用。同步只由 AI/运维 API 触发，失败不会替换现有数据库清单。
- 项目侧数据源选项接口按数据源分组返回数据库清单且不返回连接口令；浏览器只展示现有选择。本机 AI/运维批量保存时使用单个数据库事务替换该项目关联，保留仍被选中的既有策略，新关联使用默认只读限制。`mcp_alias` 虽保存在项目关联上，但更新接口、Repository 和数据库唯一索引都按 Workspace 校验。
- `database_environments.py`、`DatabaseEnvironmentRepository` 和环境 Schema 负责 Workspace 动态环境注册表、数据库关联及通用 JSON 对象。环境键按 Workspace 独立登记，保存时校验目标属于同一 Workspace 和 Project 的既有授权；多个环境允许复用同一目标。浏览器只读，AI/运维写操作递增共享 revision。
- `table_relations.py`、`TableRelationQueryService` 和 `TableRelationRepository` 只做读。存储的边是方向中立的规范化左右对，`orientation` 记录哪一端持有被指向的键，`cardinality` 统一按父到子存储；服务层按当前选中的表把 `one_to_many` 与 `many_to_one` 翻转，翻转后的基数就是相对当前表的说法，因此直接充当分组依据：`one_to_one`、`one_to_many`、`many_to_one`、`many_to_many` 四个固定顺序的分组，空组不返回，中间表的多对多合成后归入 `many_to_many`。自引用列的父端和子端是同一张表，因此同一条边同时落在 `1 — N` 和 `N — 1` 两组。**基数为 `unknown` 的边在服务层就被过滤掉**，因为左栏的四个计数存在 `tables` 表里，过滤放在前端会让计数和渲染出的行对不上；`services/table_relation_rules.py` 是读写双方共用的规则源（公共字段名单、可展示基数、基数翻转），种子脚本用它算计数。读取投影只带方向类字段（`cardinality`、`direction`、`cross_database`、`folded_into_junction`），状态、证据来源和实测指标既不落库也不返回，页面一行只有基数徽章和列名对。折叠只在服务端**标记**（`folded_into_junction`），过滤由前端完成，开关不触发请求；从中间表自身视角不返回多对多。因为折叠改变的是渲染出的行数，`tables` 接口每张表除四个基数计数外还给出 `folded_*_count` 四列，前端按开关状态做减法，左栏数字才和详情行数一致；这八个计数由 `project_table_counters()` 走详情面板同一对视图构造器算出来，种子脚本直接调它而不是另算一遍。六个接口都是只读 GET，没有 rebuild POST，因此不涉及 `browser-api-policy.ts`、`browser_read_only.py` 和系统任务过滤。关联数据的生成尚未实现，示例数据由 `scripts/seed_table_relations.py` 写入，同一份声明也供查询层测试使用。
- 工作空间根目录必须是绝对目录；项目源码和文档入口相对路径禁止绝对路径、`~`、反斜杠和 `..`，并通过真实路径校验阻止软链接越界。新文档入口必须位于 `docs/` 下并以 `AGENTS.md` 结尾。AI/运维新增、编辑和删除项目时先完成必要的磁盘验证与数据库写入，再原子更新注册表；数据库写入失败时不改变当前内存项目。
- 工作空间、数据源和项目数据库授权都没有启停开关；记录存在即参与相应的目录匹配、汇总与访问校验。
- `build_document_cache` 负责递归读取、路径校验、循环检测和正文缓存。
- Workspace 刷新先构建可选根入口并遍历全部子项目生成新的 `DocumentCache`，把所有失败入口写回对应项目后统一返回问题；任一构建失败时保留全部旧缓存。全部构建成功后再统一替换，并生成显式根树或合成根树，同时把全部项目文档合并到 Workspace 搜索和读取范围。
- `document_metadata.py` 在刷新时安全解析显式 title 和 summary。
- `markdown_search_parser.py` 剥离 Front Matter、按 fenced-code-aware ATX 章节解析并生成有界、带重叠的规范化分块。
- `document_search_repository.py` 使用 PostgreSQL `simple` FTS、`pg_trgm` 和短词精确子串查询 Workspace 或 Project 的当前索引版本；两类索引分别持久化，避免使用伪 Project。
- `ContextDocumentSearchService` 按 task scope 选择 Workspace 或旧 Project 兼容链路，校验 Workspace 根入口和各项目 index_version，将分块命中聚合为文档结果；只返回定位信息，不返回 Markdown 正文。
- `ContextPreparationService` 为 MCP 和本机 Workspace MCP JSON 预览生成同一精简返回模型。调用方可选传当前 Workspace 已登记的任意环境；显式选择写 `task_explicit`，省略固定 `local` 并写 `workspace_default`。数据库别名与通用 JSON 由 `read_task_context` 按需获取，Nacos 中间件由 `read_middleware_context` 实时获取。
- `NacosMiddlewareService` 复用 task 的 Workspace 边界；`read_middleware_context` 的显式已登记环境优先，省略时继承 task 环境，并读取同名唯一 Nacos 配置。MCP 参数不能覆盖 Nacos 地址、命名空间或字段路径；本机工具默认返回明文，显式 `reveal_secrets=false` 时脱敏。
- `task_repository.py` 为新 prepare 写入 `scope='workspace'`、Workspace 快照、可选活动项目快照、动态环境、共享 revision 和 `database_environment_selection`。新任务显式环境写 `task_explicit`，省略环境写 `workspace_default`。
- `ContextDocumentReadService` 按 task scope 校验 Workspace 聚合缓存或旧 Project 缓存，批量读取文档或章节，并在返回正文前记录调用。
- `document_read_repository.py` 保存 read_call_id、单次 position、相对路径、章节和状态，不保存正文。
- `DatabaseAccessService` 是数据库调用的授权入口。`workspace_default` 与 `task_explicit` 都要求环境仍已登记且共享 revision 一致，再按环境和稳定别名解析授权。所有链路都不接受 Host、DSN、账号或远端库名。
- `database/policy.py` 使用 SQLGlot fail-closed 校验单条只读 SQL，拒绝写入、多语句、跨数据库、外部表函数、文件/网络读取和调用方自带 SETTINGS。
- `DatabaseCatalogService` 提供 schema/table/view/column/index 的 `names`、`summary`、`full` 渐进搜索；细节越高，允许返回的对象数越少。
- `DatabaseQueryService` 执行有界只读查询；`DatabaseResultFormatter` 统一处理复杂类型、结果大小和明确截断元数据。
- `ConnectorManager` 以数据源配置版本和数据库更新时间组成缓存键，提供延迟连接、同 key single-flight、并发限制、LRU 淘汰和失效关闭。
- `database_call_repository.py` 记录 operation、数据库别名/Engine 快照、对象或语句类型、SQL SHA-256、状态、耗时、数量、字节数、截断和稳定错误码；不保存完整 SQL 或结果。
- `database_tool_payload.py` 与独立 Repository 只对白名单数据库工具自动保存有界请求和最终 MCP 响应。请求/响应默认各 1 MB、硬上限 4 MB、默认保留 7 天；启动时恢复 pending 并清理过期内容，调用期间按节流周期继续清理。
- `workspace_runtime_orchestration.py` 以 task 的 Workspace 快照为边界，负责改动归属、fast/full/start 选择、确定性步骤顺序和操作查询；`runtime_materialization.py` 生成不可变执行快照。
- `local_workspace_mapping.py` 读取项目本机 YAML，按 Workspace ID 决定卡片显示、主目录和 reader 目录。`project_registry.py` 以主目录构建唯一文档缓存；reader cwd 返回 `documents_only` 快照，数据库与运行服务按 task.cwd 再次拒绝越权。
- `workspace_shared_files.py` 扫描主目录 `docs/` 和固定 deploy 目录；`workspace_shared_file_repository.py` 在同一 PostgreSQL 事务中替换源文件副本及 Workspace/Project 运行配置。恢复操作只删除并重建主目录对应的 docs/deploy 目录。
- `runtime_runner.py` 暴露只允许 Bearer Token 且拒绝浏览器请求的注册、心跳、领取租约和完成回报协议；`scripts/context_router_host_runner.py` 是宿主机执行器。普通部署步骤只执行物化快照；`host_action` 只接受控制面和 Runner 两端共同登记的动作白名单，并把未指定环境固定为 `local`。攀枝花开机保障动作只能调用 `/Users/conchi/script/ensure-panzhihua-host-runtime.sh`，不能执行任意路径或任意命令。
- `mcp_server.py` 固定注册 22 个上下文、数据库、中间件、表关联、值映射、数据与任务可视化收件、接口转发、容器日志和 Workspace 运行工具，并挂载到 `/mcp`。项目、数据源、中间件或容器变化不会改变工具名。
- `mcp_server.py` 使用统一工具分发埋点记录全部 22 个当前工具；观测持久化失败只降低链路可见性，不改变 MCP 工具原始成功或失败结果。中间件调用摘要只记录数量与开关，不记录返回内容；Trace 查询仍识别三个已下线工具，以展示历史调用。
- `mcp_tool_call_repository.py` 保存通用工具调用和任务链路摘要；文档与数据库 Repository 继续保存各自明细，并通过可空唯一 `tool_call_id` 关联。
- `api/mcp_traces.py` 返回全局任务链路列表和单任务统一调用详情；列表支持项目、Agent、固定内部工具、调用状态和关键词的服务端过滤。普通 task 即使没有成功落下内部调用节点也能显示，`web-preview` 与 `connection-test` 系统任务除外。API 已把文档、数据库明细转换为同一 `artifacts` 数组，并返回 `complete / running / partial` 完整性状态与稳定 warning code；主详情只包含 payload 的 available/status/reason，完整 JSON 由带 `Cache-Control: no-store` 的归属校验接口懒加载。
- `mcp_integration.py` 生成客户端配置，并接收 `workspace_id`，以 MCP Python Client 对后端自身执行 initialize、tools/list、Workspace 匹配、prepare、search 和 read，不绕过协议直接调用 service。
- `GET /api/mcp/integration/tools` 直接序列化当前 FastMCP 注册表的 `tools/list` 结果，供系统文档菜单按工具拆分为独立只读项；不从系统文档表复制或维护工具定义。
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
           -> components/workspace-runtime-sync.tsx
     -> components/data-source-dashboard.tsx
     -> components/table-relation-explorer.tsx
        -> components/table-relation-table-list.tsx
        -> components/table-relation-detail.tsx
           -> components/table-relation-group.tsx
           -> components/table-relation-edge-row.tsx
              -> components/table-relation-badge.tsx
     -> lib/api.ts
     -> lib/browser-api-policy.ts
     -> lib/markdown.ts
     -> lib/table-relations.ts
```

Markdown 解析器只生成 React 元素，不使用 `dangerouslySetInnerHTML`，也不执行文档里的原始 HTML。

工作空间列表负责分类筛选、本机映射重载、摘要展示和进入详情。卡片路径及显示状态只来自本机 YAML。详情页按“前端项目 / 后端项目”两页签组织只读内容；数据源汇总位于环境详情页并跟随环境下拉框切换。“环境详情 / 查看调用记录 / 查看文档树 / 查看 MCP JSON”仍位于 Workspace 工具栏。

数据源卡片进入“查看连接”详情，保留分类筛选、连接参数和数据库清单查看、密码按需 reveal 与连接测试；工作空间的后端项目只读展示当前数据库授权。运行配置页只读展示快速/完整部署文件、历史运行状态和日志，不调用配置保存、物化或执行 API。

Workspace 调用记录通过 `task-history.ts` 保留文档读取批次和单批位置，通过 `database-access.ts` 把文档 read call 与数据库 call 按创建时间合并为上下文时间线。历史“文档树”视图在前端以被调用文档 ID 为集合递归裁剪当前 Workspace 文档树，只保留命中节点及其全部祖先，隐藏无关旁支和命中节点下未调用的后代；正常“查看文档树”仍展示完整树。后端工作空间任务列表在 `LIMIT` 前过滤既没有 read call 也没有数据库调用的任务；同一次批量读取的文档在一行横向展示，读取成功的卡片复用 Workspace 文档详情接口和 Markdown 抽屉。数据库卡片仍只展示客观摘要。

全局调用链路页由 `trace-explorer.tsx` 读取统一 Trace API，服务端直接返回 `sequence`、调用状态、完整性和关联 artifacts。页面提供任务、Agent、22 个当前工具、三个历史工具和状态筛选，只保留调用树与调用列表；“调用树”只对显式 `parent_tool_call_id` 绘制父子含义，普通调用按稳定顺序纵向排列。文档搜索节点只展示返回文档数量等脱敏摘要，文档工具不请求文档树或 Markdown；数据库工具通过 `database-call-payload-modal.tsx` 点击后懒加载全屏出入参详情。中间件工具只展示组件数量、是否显式 reveal 和警告数量。列表和详情会把链路标记为“完整 / 运行中 / 可能不完整”，并把 prepare 缺失、历史、重启中断或未关联明细转换为中文提示。

表关联页由 `table-relation-explorer.tsx` 拉取 Workspace 唯一发布版本、表清单和单表详情，不接收任务或页面环境。后端按当前选中的表完成基数视角翻转、过滤和折叠标记，前端只负责呈现。关联数据页另外携带页面环境：关系结构仍取唯一发布版本，实际数据连接由该环境映射解析。关联数据的生成尚未实现，示例数据由后端种子脚本写入。

数据可视化页不复用关联数据页的 React 状态，只复用表清单和有界查询 API。`save_data_visualization_query` 从已验证 task 补全 Workspace、动态环境、来源和 tool call 关联，`AiDataVisualizationService` 继续校验已发布关联表并按 task 条件生成稳定幂等键。关联查询携带 `ai_query_record_id`，完成后回写成功/失败、耗时、结果规模和短错误摘要；浏览器写入仍由 `BrowserReadOnlyMiddleware` 拒绝。四个可视化页面使用 task 筛选互相跳转，不共享数据管理页面状态。

任务可视化页不建立第二套任务状态机。`AiTaskVisualizationService` 直接以 `mcp_tasks.id` 聚合最近 30 天的统一工具调用、数据查询、接口转发日志和容器错误快照；详情接口同时把真实计数归一为 MCP、数据、接口、日志和结论五项链路健康状态。数据查询区分 pending/succeeded/failed，接口区分全部成功、部分失败和全部失败，未产生记录统一标记为 `unused` 而不是故障。`save_task_visualization_result` 对摘要、根因、代码位置、后续建议和验证结果递归脱敏后按 task 覆盖更新并记录 revision。列表、详情和最新在前的时间线均只读，关联按钮只在对应记录存在时显示，并带同一个 task_id 进入其他可视化页面。

接口可视化页由 `AiInterfaceVisualizationService` 聚合真实 `interface_forwarding_logs`、`mcp_tasks`、接口元数据和请求计划证据。列表使用 `created_at + id` 不透明游标，支持 task 筛选并限制为最近 30 天；请求预览、详情和复制内容统一递归脱敏。Codex/Antigravity 调用顺序为 `search_forwarding_interfaces`，按需调用 `read_forwarding_request_history`、业务值映射或只读数据库工具，再调用 `prepare_forwarding_request -> execute_forwarding_request`；页面仅观察最终真实请求。

日志可视化链路为 `prepare_task_context -> list_task_containers -> inspect_container_errors`。容器列表只来自 `runtime-runner.workspace-id` 标签；快照读取前再次校验容器归属，使用非跟随 Docker logs、默认最近 15 分钟/500 行和 512000 字节硬上限。显式关键词必须命中才记录；服务端按相邻因果签名生成稳定指纹，用合并后的错误事件累计出现次数并脱敏。列表支持 task 筛选、最近 30 天窗口和 `last_seen_at + id` 不透明游标；浏览器只读，不直接访问 Docker Socket。

ClickHouse 连接详情展示 secure、verify、bootstrap database、connect timeout 和 send/receive timeout；项目数据源详情展示 `mcp_alias` 和只读策略。AI/运维通过既有批量 API 维护时，后端仍校验同 Workspace 其他项目的别名占用，因此支持合法的别名互换且不会部分保存。历史非只读关联会明确提示不暴露给 MCP。

MCP 接入信息和测试结果通过 `lib/api.ts` 获取；公开 MCP URL 由后端配置统一提供，前端不按浏览器地址猜测。面板展示固定工具，并说明文档搜索绑定 prepare 创建的 Workspace task，真正可用的数据库以 `read_task_context` 的 `databases` 为准；中间件信息由 `read_middleware_context` 按“显式 environment 优先、省略时继承 task 环境”的规则读取。测试请求发送当前 `workspace_id`；端到端测试任务的 `agent_name` 固定为 `connection-test`，任务列表默认过滤这类记录。
