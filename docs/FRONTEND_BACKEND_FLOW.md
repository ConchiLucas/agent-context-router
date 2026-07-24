# 前后端链路速查

## 总体链路

```text
Browser
  -> Next.js 项目卡片
  -> FastAPI 项目管理 API
  -> PostgreSQL document_projects
  -> ProjectRegistry 当前运行时缓存
  -> AGENTS.md 绝对路径映射到容器只读工作区
  -> 递归解析“下级文档”表格
  -> 原子替换内存树和 Markdown 正文索引
```

```text
Codex / Antigravity
  -> POST /mcp
  -> prepare_task_context
  -> ContextPreparationService
  -> ProjectRegistry 按 cwd 定位内存树
  -> PostgreSQL mcp_tasks 生成 task_id
  -> 返回完整文档树 JSON
  -> read_context_document(task_id, requests[])
  -> ContextDocumentReadService 按 project_key 校验任务项目
  -> DocumentCache 按请求顺序返回完整 Markdown 或章节
  -> PostgreSQL 生成 read_call_id 并保存 position/status
```

```text
Codex / Antigravity
  -> prepare_task_context 返回 task_id + databases[].database(mcp_alias)
  -> search_database_objects / execute_database_query
  -> DatabaseAccessService 读取 task_id 绑定的 project_key
  -> ProjectRegistry 解析当前项目
  -> project_id + mcp_alias 一次 JOIN 读取当前关联、数据库、数据源和查询策略
  -> ConnectorRegistry 校验 Engine 能力
  -> SQL/对象范围策略与全局硬上限
  -> ConnectorManager 延迟创建或复用有界连接
  -> MySQL / MariaDB / PostgreSQL / ClickHouse Connector
  -> DatabaseResultFormatter 按对象数、行数和字节数格式化/截断
  -> PostgreSQL mcp_database_calls 保存客观调用元数据
```

```text
Codex / Antigravity
  -> POST /mcp tools/call
  -> ContextRouterMCP 统一采集工具名、task_id、开始时间和脱敏参数摘要
  -> PostgreSQL mcp_tool_calls 生成 tool_call_id
  -> ContextVar 把 tool_call_id 传给文档读取或数据库调用明细
  -> 工具完成后更新状态、结束时间、耗时、结果摘要或稳定错误码
  -> GET /api/mcp-traces[/{task_id}]
  -> 链路管理页面按服务端 sequence 展示链路图、调用列表和文档树
```

`mcp_tool_calls.id` 由 PostgreSQL Identity 生成，任务内展示顺序由后端按该 ID 计算，不依赖客户端 sequence、前端时间戳拼接或任务锁。旧文档/数据库调用由 migration 恢复为 `legacy` 节点，因此升级后仍可查看历史记录。

prepare 不建立业务数据库连接。业务数据库离线时，`/health`、文档 prepare 和文档 read 仍可工作；MCP 链路只有实际对象搜索或查询会尝试连接，管理页面的连接测试和数据库同步也会显式连接。

## 页面到 API

| 页面行为 | 前端 | 后端 API |
| --- | --- | --- |
| 加载项目卡片 | `project-dashboard.tsx` | `GET /api/projects` |
| 按项目类型切换卡片 | `project-dashboard.tsx` | 复用 `GET /api/projects` 返回的 `project_type` 在前端筛选 |
| 按数据源分类切换卡片 | `data-source-dashboard.tsx` | 复用 `GET /api/data-sources` 返回的 `category` 在前端筛选 |
| 按需查看数据源密码 | `data-source-dashboard.tsx` | `POST /api/data-sources/{id}/reveal-password`，响应禁止缓存 |
| 加载 Engine 能力矩阵 | `data-source-dashboard.tsx` | `GET /api/data-source-engines` |
| 测试当前连接 | `data-source-dashboard.tsx` | `POST /api/data-sources/{id}/test`，返回状态、耗时和短错误码 |
| 同步 MySQL/MariaDB/PostgreSQL/ClickHouse 可见库 | `data-source-dashboard.tsx` | `POST /api/data-sources/{id}/databases/sync` -> `database_discovery.py` -> 事务 upsert 清单 |
| 添加项目 | `project-dashboard.tsx` | `POST /api/projects` |
| 编辑项目 | `project-dashboard.tsx` | `PUT /api/projects/{id}` |
| 停用/启用项目 | `project-dashboard.tsx` | `PATCH /api/projects/{id}/enabled` |
| 删除项目配置 | `project-dashboard.tsx` | `DELETE /api/projects/{id}` |
| 刷新映射 | `project-dashboard.tsx` | `POST /api/projects/{id}/refresh` |
| 打开全屏树 | `document-tree.tsx` | `GET /api/projects/{id}/tree` |
| 点击节点查看详情 | `markdown-viewer.tsx` | `GET /api/projects/{id}/documents/{document_id}` |
| 查看 MCP JSON | `project-dashboard.tsx` | `POST /api/projects/{id}/prepare-preview` |
| 查看调用记录 | `project-dashboard.tsx`、`task-history.ts` | `GET /api/projects/{id}/tasks`、`GET /api/tasks/{task_id}/document-reads` |
| 查看全局 MCP 链路 | `trace-explorer.tsx`、`mcp-traces.ts` | `GET /api/mcp-traces`、`GET /api/mcp-traces/{task_id}` |
| 加载项目可选数据源和库 | `project-dashboard.tsx` | `GET /api/projects/{id}/data-source-options` |
| 原子保存项目数据库选择与全部 MCP 别名 | `project-dashboard.tsx` | `PUT /api/projects/{id}/databases` |
| 单独编辑一个 MCP 别名（兼容接口） | API 调用方 | `PATCH /api/projects/{project_id}/databases/{link_id}/mcp-alias` |
| 打开 MCP 接入面板 | `mcp-integration-panel.tsx` | `GET /api/mcp/integration` |
| 执行 MCP 连接测试 | `mcp-integration-panel.tsx` | `POST /api/mcp/integration/tests` |

## 后端代码

```text
api/projects.py
  -> services/project_registry.py
  -> services/document_tree.py
  -> schemas/projects.py
```

- `ProjectRegistry` 管理多个进程内项目和每个项目的当前缓存。
- `project_repository.py` 持久化稳定项目配置及项目类型；后端启动时读取所有项目，启用项目从磁盘重建缓存，停用或路径失效项目保留配置但不参与 cwd 匹配。
- 项目类型仅用于管理页面分类和筛选，不参与 MCP 的 cwd 项目匹配。
- 数据源分类由 `data_sources.category` 独立持久化，仅用于数据源管理页面分类和筛选，不复用项目类型。
- 数据源列表始终过滤口令；只有编辑弹窗的眼睛按钮调用独立接口读取明文密码。连接测试使用临时 Connector，完成后关闭，不进入长期缓存，也不向响应暴露连接配置。
- MySQL/MariaDB/PostgreSQL/ClickHouse 自动同步由 `database_discovery.py` 使用对应驱动读取远端数据库清单，保留已有记录 ID 和项目关联，新增可见库并把本次未发现的旧库标记为不可用。同步失败不会替换现有数据库清单。
- 项目侧数据源选择接口按数据源分组返回数据库清单且不返回连接口令；批量保存使用单个数据库事务替换该项目关联，保留仍被选中的既有策略，新关联使用默认只读限制。`mcp_alias` 另有项目作用域更新接口和数据库唯一约束。
- 项目新增、编辑、启停和删除先完成必要的磁盘验证与数据库写入，再原子更新注册表；数据库写入失败时不改变当前内存项目。
- `build_document_cache` 负责递归读取、路径校验、循环检测和正文缓存。
- 刷新完成后，`ProjectRegistry` 一次性替换该项目的 `DocumentCache`。
- `document_metadata.py` 在刷新时安全解析显式 title 和 summary。
- `ContextPreparationService` 为 MCP 和卡片 JSON 预览生成同一个返回模型；除完整文档树外，还从本地持久化配置生成可用数据库摘要，不 ping 远端数据库。
- `ContextDocumentReadService` 校验 task/project、批量读取文档或章节，并在返回正文前记录调用。
- `document_read_repository.py` 保存 read_call_id、单次 position、相对路径、章节和状态，不保存正文。
- `DatabaseAccessService` 是数据库调用的授权入口，固定执行 `task_id -> project -> mcp_alias -> 当前连接/策略`；它只接受 prepare 返回的项目内别名，不接受 Host、DSN、账号或远端库名。
- `database/policy.py` 使用 SQLGlot fail-closed 校验单条只读 SQL，拒绝写入、多语句、跨数据库、外部表函数、文件/网络读取和调用方自带 SETTINGS。
- `DatabaseCatalogService` 提供 schema/table/view/column/index 的 `names`、`summary`、`full` 渐进搜索；细节越高，允许返回的对象数越少。
- `DatabaseQueryService` 执行有界只读查询；`DatabaseResultFormatter` 统一处理复杂类型、结果大小和明确截断元数据。
- `ConnectorManager` 以数据源配置版本和数据库更新时间组成缓存键，提供延迟连接、同 key single-flight、并发限制、LRU 淘汰和失效关闭。
- `database_call_repository.py` 记录 operation、数据库别名/Engine 快照、对象或语句类型、SQL SHA-256、状态、耗时、数量、字节数、截断和稳定错误码；不保存完整 SQL 或结果。
- `mcp_server.py` 固定注册 `prepare_task_context`、`read_context_document`、`search_database_objects`、`execute_database_query`，并挂载到 `/mcp`。数据源变化不会改变工具名。
- `mcp_server.py` 使用统一工具分发埋点记录四个固定工具；观测持久化失败只降低链路可见性，不改变 MCP 工具原始成功或失败结果。
- `mcp_tool_call_repository.py` 保存通用工具调用和任务链路摘要；文档与数据库 Repository 继续保存各自明细，并通过可空唯一 `tool_call_id` 关联。
- `api/mcp_traces.py` 返回全局任务链路列表和单任务统一调用详情；API 已把文档、数据库明细转换为同一 `artifacts` 数组，前端不再自行跨表推断调用顺序。
- `mcp_integration.py` 生成客户端配置，并以 MCP Python Client 对后端自身执行 initialize、tools/list、prepare 和 read，不绕过协议直接调用 service。
- 接入测试只返回阶段状态、耗时、task_id、read_call_id 和正文字符数；数据库 URL 与 Markdown 正文不进入 API 响应，且该测试不执行项目业务数据库查询。

## Engine 能力矩阵

| Engine | 配置管理 | 连接测试 | 同步数据库 | 对象搜索 | 有界只读查询 |
| --- | --- | --- | --- | --- | --- |
| MySQL | 是 | 是 | 是 | 是 | 是 |
| MariaDB | 是 | 是 | 是 | 是 | 是 |
| PostgreSQL | 是 | 是 | 是 | 是 | 是 |
| ClickHouse | 是 | 是 | 是 | 是 | 是 |
| SQL Server | 是 | 否 | 否 | 否 | 否 |
| SQLite | 是 | 否 | 否 | 否 | 否 |
| Oracle | 是 | 否 | 否 | 否 | 否 |

前端必须以 `GET /api/data-source-engines` 的响应为真值，不通过静态 Engine 列表推断按钮或“MCP 可查询”状态。

## 前端代码

```text
app/page.tsx
  -> components/project-dashboard.tsx
     -> components/document-tree.tsx
     -> components/markdown-viewer.tsx
     -> components/mcp-integration-panel.tsx
     -> lib/api.ts
     -> lib/markdown.ts
```

Markdown 解析器只生成 React 元素，不使用 `dangerouslySetInnerHTML`，也不执行文档里的原始 HTML。

调用记录通过 `task-history.ts` 保留文档读取批次和单批位置，通过 `database-access.ts` 把文档 read call 与数据库 call 按创建时间合并为上下文时间线。同一次批量读取的文档在一行横向展示；数据库卡片展示 operation、别名、Engine、对象/语句类型、状态、耗时、数量、字节数和截断。文档树节点角标仍只表达文档读取批次，读取成功的卡片复用文档详情接口和 Markdown 抽屉。

全局链路管理由 `trace-explorer.tsx` 读取统一 Trace API，服务端直接返回 `sequence`、调用状态和关联 artifacts。页面复用 `DocumentTree`、Markdown 详情、文档批次角标和多文档横排样式；“链路图”只对显式 `parent_tool_call_id` 绘制父子含义，普通调用按稳定顺序纵向排列。

ClickHouse 编辑表单保留 secure、verify、bootstrap database、connect timeout 和 send/receive timeout；项目数据库弹窗实时校验 `mcp_alias` 格式和项目内重复值，并将选择与别名放在一个后端事务中提交，因此支持两个别名直接互换且不会部分保存。历史非只读关联会明确提示不暴露给 MCP。

MCP 接入信息和测试结果通过 `lib/api.ts` 获取；公开 MCP URL 由后端配置统一提供，前端不按浏览器地址猜测。面板展示四个固定工具，并说明任务真正可用的数据库以 prepare 的 `databases` 为准。端到端测试任务的 `agent_name` 固定为 `connection-test`，任务列表默认过滤这类记录。
