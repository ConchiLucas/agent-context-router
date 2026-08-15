# 数据库信息

当前版本使用宿主机已有的 PostgreSQL 作为控制面数据库，持久化工作空间与项目配置、数据源配置、可选 TEST/UAT 数据库环境映射及通用环境 JSON、Workspace Nacos 中间件配置档、MCP task、文档读取顺序、数据库调用元数据，以及可重建的文档词法搜索索引。文档树和 Markdown 原文仍以磁盘与进程内缓存为真源，文档与中间件 MCP 完整出入参不会写入控制面数据库；两个数据库 MCP 工具会另存有界、可过期的请求与最终响应快照，供本机页面按需查看。

PostgreSQL 控制面数据库与 MCP 查询的业务数据库是两个概念。业务数据库目前可执行的 Connector 为 ClickHouse、PostgreSQL、MySQL 和 MariaDB；SQL Server、SQLite、Oracle 的配置仍可由本机 AI/运维 API 维护，但能力接口会明确标记为不可搜索、不可查询。

浏览器页面以读取控制面数据为主，只允许通过专用接口保存已有 `system_guides` 的 JSON 正文，不能新建、删除或修改记录元数据。Workspace、Project、数据源、授权、环境和运行配置仍保持浏览器只读；其他配置写请求由后端返回 `405 management_read_only`。不携带浏览器识别头的本机 AI/运维调用方仍可使用既有受 Schema、Service 和 Repository 校验的 API，避免直接写表而绕过环境 revision、文档缓存或 Connector 失效处理。

## 连接配置

通过 `.env` 提供连接串，仓库不保存真实账号口令：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/context_router
```

后端容器通过 `host.docker.internal` 访问宿主机 PostgreSQL，不再启动项目自己的 PostgreSQL 容器。

## Migration

```bash
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run alembic current
```

当前 head 为 `20260813_0034`。`0034 -> 0033` 会删除模板预处理证据的 Profile、规则链和候选审计字段；`0033 -> 0032` 会删除表关联结构化跳过诊断并移除完整 warning 计数；`0032 -> 0031` 会删除可重建的 SQL 表关联批次、关系、字段对和证据；`0029` 至 `0031` 是已回滚实验功能的无操作兼容标记；`0028 -> 0027` 会删除全部 Workspace Nacos 配置档；`0025 -> 0024` 会删除全部统一系统 JSON 文档；`0024 -> 0023` 会删除数据库中的 Workspace 文档与部署源文件副本，不影响目标目录现有文件。若要验证 downgrade/upgrade，使用一次性测试数据库，不要在保存真实数据的控制面库上直接 downgrade。

`system_guides` 保存 `guide_key`、JSONB 正文、菜单顺序和时间戳，没有 `enabled` 字段。历史 `include_in_prepare` 字段不再影响 MCP prepare；记录只进入系统文档菜单。

## 当前表

| 表 | 用途 |
| --- | --- |
| `workspaces` | 保存顶层工作空间 ID、名称、类型、唯一绝对根目录和创建/更新时间；记录存在即参与 cwd 匹配 |
| `workspace_shared_files` | 保存主映射目录 `docs/` 与各 `deploy/context-router/` 的 UTF-8 源文件副本；按 Workspace、类型和相对路径唯一，用于双向全量覆盖 |
| `document_projects` | 保存稳定项目 ID、名称、`frontend/backend` 的 `project_kind`、所属 `workspace_id`、工作空间内分别唯一的源码 `relative_path` 与文档入口 `document_relative_path`、兼容 `project_type`/`agents_path` 和创建/更新时间；没有 Project enabled |
| `data_sources` | 保存物理数据库连接、独立数据源分类、数据库类型和连接参数；密码不进入列表 API，仅可由本机页面通过独立 no-store 接口按需读取 |
| `data_source_databases` | 保存每个物理连接下可供项目选择的实际库、schema 或 SQLite 文件清单 |
| `project_databases` | 保存 `workspace_id`、具体项目与数据库的多对多关联、人类展示别名、Workspace 内大小写无关唯一的 `mcp_alias`、用途和只读/查询限制策略 |
| `workspace_database_environment_configs` | 保存 Workspace 环境选择器、当前 `test/uat` 环境和单调递增 revision；是否采用数据库环境映射由映射记录是否存在决定 |
| `workspace_environment_payloads` | 按 Workspace 与 `test/uat` 以明文 JSONB 保存受大小/深度限制的 JSON 对象；可按明确业务需要包含地址和访问凭据，task 所选环境内容只在显式调用 `read_task_context` 时返回给可信本机 MCP 调用方，严禁进入日志、开发文档、链路摘要或示例输出 |
| `workspace_nacos_profiles` | 按 Workspace 与 `default/test/uat` 保存 Nacos 地址、命名空间、登录凭据、超时及声明式组件抽取规则；列表 API 不返回密码，本机 `read_middleware_context` 默认返回明文且可显式关闭 reveal 获取脱敏视图，实际响应不进入 Trace 或 payload 表 |
| `project_database_environment_mappings` | 保存 Project 逻辑数据库、跨环境稳定 `mcp_alias` 和 Workspace 归属 |
| `project_database_environment_targets` | 把每条逻辑映射的 `test/uat` 目标绑定到既有 `project_databases` 授权；不复制连接和查询策略 |
| `mcp_tasks` | 保存 prepare 产生的自增 task_id、`project/workspace` scope、Workspace ID/key/name、可选活动项目快照、可选数据库环境、共享 revision 与 `workspace_default/task_explicit` 选择模式，以及兼容旧 Project task 的 project_id/project_key/name |
| `mcp_document_read_calls` | 保存每次 read 的自增 read_call_id、task_id 和创建时间 |
| `mcp_document_read_items` | 保存单次 read 内的 position、文档 ID、相对路径、章节、状态和错误码 |
| `mcp_database_calls` | 保存对象搜索或只读查询的 task_id、数据库 alias、Engine、SQL SHA-256、状态、耗时、返回规模、截断和错误码；不保存 SQL 正文和结果集 |
| `mcp_tool_calls` | 保存任务下每次 Context Router MCP 工具调用的 Server、工具名、服务端顺序依据、来源、状态、时间、耗时和脱敏摘要；文档/数据库明细通过 tool_call_id 关联 |
| `mcp_database_tool_payloads` | 按 tool_call_id 一对一保存两个数据库 MCP 工具的有界请求、最终 MCP 响应、字节数、截断、采集状态和到期时间；普通 Trace 查询不加载 payload |
| `document_search_index_states` | 保存每个项目当前搜索索引的文档版本、索引格式版本、文档/分块数量和完成时间 |
| `document_search_chunks` | 保存从 Markdown 派生的规范化章节分块、路径/标题/概要、`simple` tsvector 和 trigram 检索文本；可由磁盘原文完整重建 |
| `workspace_document_search_index_states` | 保存可选 Workspace 根文档树当前搜索索引的版本、规模和完成时间 |
| `workspace_document_search_chunks` | 保存 Workspace 根 `AGENTS.md` 及其下级文档的规范化派生分块；与 Project 索引独立并可重建 |
| `agent_context_router_alembic_version` | 当前精简应用的 migration 版本；与 context_router 库内历史 `alembic_version` 隔离 |

task_id、tool_call_id 和 read_call_id 都由 PostgreSQL identity 自动生成；任务内调用顺序按 tool_call_id 计算，单次读取顺序来自请求数组 position。客户端不传序号，也不维护每任务计数器或锁。数据库不保存文档树或 Markdown 原文，只保存由当前版本派生的规范化搜索分块。

`20260724_0009` 会把已有文档读取和数据库调用按历史时间恢复为 `legacy` 工具调用，并回写明细表的 `tool_call_id`；历史数据没有 prepare 事件或可靠开始时间，因此不会补造 prepare 节点，页面也会明确标记“历史记录”。`20260724_0010` 会按旧 `project_key` 为可匹配的历史任务回填稳定 `project_id`。`20260725_0011` 新增数据库工具 payload 表，不为历史调用反向生成无法确认的出入参。`20260725_0012` 启用 `pg_trgm` 并新增文档搜索索引表；扩展在 downgrade 时保留，索引数据可从磁盘 Markdown 重建。

`20260726_0013` 新增 `workspaces`，并为 `document_projects` 增加非空 `workspace_id` 和 `relative_path`。升级时每个旧项目会生成一个同 ID 工作空间：`root_path` 取旧 `agents_path` 的父目录，工作空间默认启用，原项目设置为 `relative_path='.'`。原项目主键不变，因此数据库授权、文档搜索索引、文档读取和数据库/工具调用历史不需要迁移到新 ID；`document_projects.workspace_id` 使用 `ON DELETE CASCADE` 外键，同一工作空间内 `(workspace_id, relative_path)` 唯一。

`20260726_0014` 把上下文运行时边界正式提升到 Workspace：

- `document_projects` 增加受 Check Constraint 约束的 `project_kind`，旧记录默认回填为 `backend`，并删除 `enabled` 列和相关索引。
- `project_databases` 增加非空 `workspace_id` 与级联外键，唯一索引从 `(project_id, lower(mcp_alias))` 改为 `(workspace_id, lower(mcp_alias))`。升级会先检测 Workspace 内重复 alias；存在冲突时明确失败，要求先清理数据。
- `mcp_tasks` 增加 `scope`、Workspace ID/key/name 和可选活动项目 ID/name/kind。升级前的记录保持 `scope='project'`，同时根据原项目回填 Workspace/活动项目快照；新 prepare 写入 `scope='workspace'`。
- Workspace task 的 read/search/database 按 Workspace 快照解析；旧 Project task 继续按稳定 project_id，缺失时按 project_key 兼容解析，因此升级不会扩大旧 task 权限或让同路径新项目接管历史。

`20260726_0015` 为可选的 Workspace 根 `AGENTS.md` 新增独立搜索状态表和分块表，两表都按 `workspace_id` 外键级联清理。迁移不回填 Markdown 或分块；后端启动或刷新时从磁盘重建。Project 搜索表和旧 `scope='project'` task 的范围保持不变。

`20260727_0016` 为 `document_projects` 增加非空 `document_relative_path`，根据旧 `agents_path` 相对 Workspace 根目录的位置回填，并增加 `(workspace_id, document_relative_path)` 唯一约束。`relative_path` 从此只表示源码目录；兼容 `agents_path` 由 Workspace 根目录和文档入口相对路径同步生成。迁移本身不移动宿主机 Markdown，具体工作空间应先准备新入口，再通过项目编辑接口逐项迁移。

`20260728_0017` 增加项目快速/完整更新的运行配置文件，`20260728_0018` 增加 Runtime Runner 异步执行记录。`20260730_0019` 增加 Workspace 环境配置、逻辑数据库映射和 TEST/UAT 目标表，并给 `mcp_tasks` 增加环境及 revision 快照。迁移不会自动猜测或写入映射；未配置 Workspace 继续走原有 `project_databases` 解析链。

`20260730_0020` 增加 `workspace_environment_payloads` JSONB 表。两条环境 JSON 引用同一 Workspace 环境选择器，可在没有数据库映射时独立建立选择器，此时数据库继续使用原有 Workspace alias；存在数据库映射记录后才进入严格的环境目标解析。保存 JSON、保存数据库映射和切换环境共用 revision。迁移不自动读取 Nacos 或其他配置中心，也不复制任何凭据。

`20260730_0021` 为 `mcp_tasks` 增加 `database_environment_selection`。升级时，先把旧约束可能放行的半截环境/revision 快照归一为空，再把所有完整的既有环境 task 回填为 `workspace_default`；新 task 在省略 prepare 的 `environment` 参数时写入 `workspace_default`，显式选择 `test/uat` 时写入 `task_explicit`。数据库环境、revision 和选择模式必须同时为空或同时有效。

`20260730_0022` 删除 `workspaces`、`data_sources`、`project_databases` 和 `workspace_database_environment_configs` 的 `enabled` 列，并把相关查询索引重建为不含启停字段的索引。当前状态模型中记录存在即生效；数据库是否可供 MCP 查询继续由数据库 `available/system_database`、授权 `readonly`、MCP 别名和 Connector 能力共同决定。

数据库 payload 采集默认自动运行。请求和响应各限 1 MB、保留 7 天、硬上限 4 MB。保存的是已经过查询行数和结果字节预算处理、实际返回给 MCP 客户端的最终结构，不是 Connector 的原始无限结果。超出快照预算时优先按 `objects` 或 `rows` 保留前部元素并写入 `_capture` 截断标记；到期清理会删除 JSON 内容但保留 `expired` 状态。采集和清理都是 best-effort，失败不会改变原 MCP 调用结果。

本机 AI/运维通过受校验 API 创建、编辑、调整类型、启停和删除工作空间时写入 `workspaces`；在工作空间内创建、编辑和删除项目时写入 `document_projects`。浏览器只读取这些记录。源码根由 `workspaces.root_path + document_projects.relative_path` 定位，文档入口由 `workspaces.root_path + document_projects.document_relative_path` 定位；兼容 `agents_path` 和 `project_type` 仍由 Repository 同步维护，供旧 API 和旧代码路径平滑过渡。

数据源以全局物理连接为单位保存在 `data_sources`，拥有与工作空间类型完全独立的分类字段，未显式指定时默认归入“本机电脑”；一个连接可包含多个库。授权记录仍归属具体项目，并由 `project_databases` 持久化；alias 唯一约束和 MCP 解析范围都是 Workspace。浏览器连接详情和项目数据源详情只读展示这些记录，实际维护由 AI/运维调用既有 API。工作空间汇总 API 只 JOIN 其项目的现有授权，按物理数据源/数据库去重并返回每条授权的当前状态，不复制授权或改变 MCP 策略。批量保存会在一个事务中替换指定项目的关联，同时校验同 Workspace 其他项目已经占用的 alias；保留仍被选中的既有查询策略，新关联使用默认只读限制。当前版本不加密本地连接参数，列表 API 会过滤所有口令；只有用户在只读详情点击眼睛时才通过 `POST /api/data-sources/{id}/reveal-password` 按需读取，并明确禁止缓存响应。MySQL/MariaDB/PostgreSQL/ClickHouse 的数据库清单可由 AI/运维从远端同步，已不存在或当前账号不可见的旧库只标记 `available=false`，不直接删除项目关联。ClickHouse 使用官方 `clickhouse-connect` HTTP/HTTPS Client；后端容器访问宿主机服务时 Host 使用 `host.docker.internal`。

没有配置环境选择器的单环境 Workspace 继续使用 `task_id -> task.workspace_id/workspace_key -> Workspace 唯一 mcp_alias -> 所属 Project Link/Database/Source 当前状态与策略` 的旧解析链；省略 prepare 的 `environment` 参数保持旧行为，显式传入 `test/uat` 返回 `environment_not_configured`。配置选择器后，省略参数会把当前 Workspace 环境固化为 `workspace_default`，显式参数会把所选环境固化为 `task_explicit` 且不修改 Workspace 当前环境。只配置通用 JSON 时数据库仍使用 legacy alias；存在数据库映射记录后，同一稳定 alias 按 task 固化环境解析目标授权。两种选择模式的调用都先比对共享 revision，保存 JSON、保存映射或切换当前环境造成 revision 变化后返回 `environment_changed`，要求客户端重新 prepare。数据库链路始终重新校验当前工作空间、授权、连接和只读策略；数据库可用、非系统库、`readonly=true` 且存在 MCP 别名的授权才会进入数据库摘要。环境选择器配置后，历史 `scope='project'` task 的数据库调用同样必须重新 prepare。

查询限制取项目关联值与服务硬上限的较小值。当前硬上限由以下环境变量控制：

```text
CONTEXT_ROUTER_DATABASE_MAX_ROWS=5000
CONTEXT_ROUTER_DATABASE_MAX_RESULT_BYTES=4000000
CONTEXT_ROUTER_DATABASE_MAX_QUERY_TIMEOUT_MS=30000
CONTEXT_ROUTER_DATABASE_MAX_CACHED_CONNECTORS=16
CONTEXT_ROUTER_DATABASE_MAX_CONCURRENCY_PER_SOURCE=4
CONTEXT_ROUTER_DATABASE_SCHEMA_RESULT_BYTES=1000000
```

连接参数当前按本机单用户边界以明文 JSON 保存；列表 API、MCP 结果、调用历史和公开错误均不回显口令或驱动堆栈。数据库账号仍应使用只读账号，SQL AST 校验不能替代数据库权限。

后端重启后先恢复工作空间，再按原项目 ID 恢复全部项目记录并从各自文档入口重建项目缓存，以当前缓存版本重建或确认词法索引；不会从环境变量自动创建默认 Workspace/Project。路径失效的项目保留配置并记录加载错误。工作空间没有运行时启停开关，记录存在即参与 cwd 路由；路由按最长根路径选择 Workspace，再按源码 `relative_path` 的最深 Project 记录活动项目，不使用 docs 入口目录判断。文档导航树遵循真实根的显式层级或使用合成根，search/read 和数据库授权仍覆盖整个 Workspace。搜索只读取与各项目当前缓存 index_version 一致的记录，索引缺失、失败或过期时返回明确错误，不使用内存扫描兜底。控制面数据库不可用时不会自动创建默认配置，MCP prepare/search/read、Workspace MCP JSON 和调用记录会返回明确错误。
