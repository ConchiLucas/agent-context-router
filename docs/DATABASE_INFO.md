# 数据库信息

当前版本使用宿主机已有的 PostgreSQL 作为控制面数据库，持久化项目配置、数据源管理配置、MCP 任务、文档读取顺序、数据库调用元数据，以及可重建的文档词法搜索索引。文档树和 Markdown 原文仍以磁盘与进程内缓存为真源，文档 MCP 完整出入参不会写入控制面数据库；只有显式启用 payload 采集后，两个数据库 MCP 工具才会另存有界、可过期的请求与最终响应快照，供本机页面按需查看。

PostgreSQL 控制面数据库与 MCP 查询的业务数据库是两个概念。业务数据库目前可执行的 Connector 为 ClickHouse、PostgreSQL、MySQL 和 MariaDB；SQL Server、SQLite、Oracle 仍可维护配置，但能力接口会明确标记为不可搜索、不可查询。

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

当前 head 为 `20260725_0012`。若要验证 downgrade/upgrade，使用一次性测试数据库，不要在保存真实调用记录的控制面库上直接 downgrade，因为 `0012 -> 0011` 会删除文档搜索索引与索引状态，`0011 -> 0010` 会删除数据库 MCP 出入参详情，`0010 -> 0009` 会删除任务上的稳定项目快照，`0009 -> 0008` 会删除统一 MCP 工具链路，`0008 -> 0007` 会删除数据库调用历史和 MCP alias 列。

## 当前表

| 表 | 用途 |
| --- | --- |
| `document_projects` | 保存稳定项目 ID、名称、项目类型、AGENTS.md 宿主机路径、启停状态和创建/更新时间 |
| `data_sources` | 保存物理数据库连接、独立数据源分类、数据库类型、启停状态和连接参数；密码不进入列表 API，仅可由本机页面通过独立 no-store 接口按需读取 |
| `data_source_databases` | 保存每个物理连接下可供项目选择的实际库、schema 或 SQLite 文件清单 |
| `project_databases` | 保存项目与具体数据库的多对多关联、人类展示别名、项目内大小写无关唯一的 `mcp_alias`、用途和只读/查询限制策略 |
| `mcp_tasks` | 保存 prepare 产生的自增 task_id、稳定 project_id 快照、兼容旧记录的 project_key、项目名称、任务原文、cwd、Agent 和创建时间 |
| `mcp_document_read_calls` | 保存每次 read 的自增 read_call_id、task_id 和创建时间 |
| `mcp_document_read_items` | 保存单次 read 内的 position、文档 ID、相对路径、章节、状态和错误码 |
| `mcp_database_calls` | 保存对象搜索或只读查询的 task_id、数据库 alias、Engine、SQL SHA-256、状态、耗时、返回规模、截断和错误码；不保存 SQL 正文和结果集 |
| `mcp_tool_calls` | 保存任务下每次 Context Router MCP 工具调用的 Server、工具名、服务端顺序依据、来源、状态、时间、耗时和脱敏摘要；文档/数据库明细通过 tool_call_id 关联 |
| `mcp_database_tool_payloads` | 按 tool_call_id 一对一保存两个数据库 MCP 工具的有界请求、最终 MCP 响应、字节数、截断、采集状态和到期时间；普通 Trace 查询不加载 payload |
| `document_search_index_states` | 保存每个项目当前搜索索引的文档版本、索引格式版本、文档/分块数量和完成时间 |
| `document_search_chunks` | 保存从 Markdown 派生的规范化章节分块、路径/标题/概要、`simple` tsvector 和 trigram 检索文本；可由磁盘原文完整重建 |
| `agent_context_router_alembic_version` | 当前精简应用的 migration 版本；与 context_router 库内历史 `alembic_version` 隔离 |

task_id、tool_call_id 和 read_call_id 都由 PostgreSQL identity 自动生成；任务内调用顺序按 tool_call_id 计算，单次读取顺序来自请求数组 position。客户端不传序号，也不维护每任务计数器或锁。数据库不保存文档树或 Markdown 原文，只保存由当前版本派生的规范化搜索分块。

`20260724_0009` 会把已有文档读取和数据库调用按历史时间恢复为 `legacy` 工具调用，并回写明细表的 `tool_call_id`；历史数据没有 prepare 事件或可靠开始时间，因此不会补造 prepare 节点，页面也会明确标记“历史记录”。`20260724_0010` 会按旧 `project_key` 为可匹配的历史任务回填稳定 `project_id`。`20260725_0011` 新增数据库工具 payload 表，不为历史调用反向生成无法确认的出入参。`20260725_0012` 启用 `pg_trgm` 并新增文档搜索索引表；扩展在 downgrade 时保留，索引数据可从磁盘 Markdown 重建。

数据库 payload 采集默认自动运行。请求和响应各限 1 MB、保留 7 天、硬上限 4 MB。保存的是已经过查询行数和结果字节预算处理、实际返回给 MCP 客户端的最终结构，不是 Connector 的原始无限结果。超出快照预算时优先按 `objects` 或 `rows` 保留前部元素并写入 `_capture` 截断标记；到期清理会删除 JSON 内容但保留 `expired` 状态。采集和清理都是 best-effort，失败不会改变原 MCP 调用结果。

项目创建、编辑、类型调整、启停和删除会同步写入 `document_projects`；未显式指定类型的项目默认归入“公司项目”。数据源以物理连接为单位保存在 `data_sources`，拥有与项目类型完全独立的分类字段，未显式指定时默认归入“本机电脑”；一个连接可包含多个库，项目通过“管理数据源”一次选择一个或多个连接下的多个库，并由 `project_databases` 持久化。批量保存会在一个事务中替换指定项目的关联，保留仍被选中的既有查询策略，新关联使用默认只读限制。当前版本不加密本地连接参数，列表 API 会过滤所有口令；编辑时口令留空会保留原值，只有用户点击眼睛时才通过 `POST /api/data-sources/{id}/reveal-password` 按需读取，并明确禁止缓存响应。MySQL/MariaDB/PostgreSQL/ClickHouse 的数据库清单可从远端自动同步，已不存在或当前账号不可见的旧库只标记 `available=false`，不直接删除项目关联。ClickHouse 使用官方 `clickhouse-connect` HTTP/HTTPS Client；后端容器访问宿主机服务时 Host 使用 `host.docker.internal`。

数据库 MCP 的唯一解析链是 `task_id -> task.project_id -> 当前 project -> mcp_alias -> 当前 Link/Database/Source 状态与策略`；仅未回填成功的旧任务才用 `project_key` 兼容解析。`project_id` 是任务创建时的不可变快照，不设置项目表外键：新任务和已回填任务在项目删除后仍保留原 ID，同一路径重建的新项目也不会接管它们。migration 前项目已不存在、无法按 key 回填的旧任务会保持 `project_id=NULL`。每次调用重新读取当前状态，不把权限和连接配置冻结在 prepare 快照中。只有启用、可用、非系统库且 `readonly=true` 的关联会出现在 prepare 数据库摘要中。

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

后端重启后按原项目 ID 恢复全部记录：启用项目重新读取磁盘文档，并以当前缓存版本重建或确认词法索引；停用项目不建立缓存，路径失效的项目保留配置并记录加载错误。搜索只读取与当前缓存 index_version 一致的记录，索引缺失、失败或过期时返回明确错误，不使用内存扫描兜底。数据库不可用时，项目页面仍可依靠环境变量默认项目临时运行，但新增项目和数据源配置无法跨重启保存，MCP prepare/search/read、卡片 MCP JSON 和调用记录会返回明确错误。
