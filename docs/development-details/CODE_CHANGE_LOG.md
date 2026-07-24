# 代码变更记录

本文件用于记录跨模块、数据结构、接口 contract、工程约定等重要代码变更。

## 记录规则

- 按日期追加记录。
- 只记录代码层面的开发信息，不记录普通聊天。
- 简要结论可同步到 `../DEVELOPMENT_OUTLINE.md`。
- 如果内容影响启动、数据库、业务功能或链路流转，需要同步更新对应文档。

## 记录

### 2026-07-24

- 新增 migration `20260724_0009` 和 `mcp_tool_calls` 通用链路表；文档读取、数据库调用增加可空唯一 `tool_call_id`，既有历史按时间恢复为 `legacy` 调用。
- FastMCP 四个固定工具接入统一调用观测，记录 Server、工具名、状态、起止时间、耗时、稳定错误码及脱敏摘要；prepare 成功后关联新 task，后续调用在执行前生成运行中节点，观测失败不影响业务调用。
- 新增统一 MCP Trace 列表和详情 API，服务端返回稳定 sequence 与文档/数据库 artifacts，保留旧任务历史接口兼容。
- 前端增加“链路管理”一级导航，提供任务搜索和 Agent/MCP Server/状态筛选，以及链路图、调用列表、文档树和脱敏调用详情；复用文档树、Markdown 弹窗与批量文档横排交互。

### 2026-07-22

- 新增 migration `20260722_0008`：为 `project_databases` 增加稳定、项目内大小写无关唯一的 `mcp_alias` 并回填旧关联；新增 `mcp_database_calls`，只记录数据库对象搜索/查询元数据与 SQL SHA-256，不保存 SQL 或结果。
- 新增数据库 Connector 核心层：静态 Registry、能力矩阵、lazy ConnectorManager、single-flight、lease/retiring、配置失效、LRU、每 Source 并发限制和应用退出关闭；实现 ClickHouse、PostgreSQL、MySQL/MariaDB Connector。
- 新增 SQLGlot fail-closed 只读与作用域校验，拒绝多语句、写操作、跨库/未授权 Schema、系统目录、ClickHouse SETTINGS/FORMAT/OUTFILE 与外部文件/网络 table function；查询结果增加行数、最终 JSON 字节和复杂类型规范化预算。
- MCP 从两个静态工具扩展为四个，新增 `search_database_objects` 与 `execute_database_query`；prepare 返回当前项目可用只读数据库的最小摘要，数据库调用统一按 `task_id -> project -> mcp_alias -> live policy` 路由。
- 数据源管理新增 Engine 能力接口、连接测试、ClickHouse TLS/verify/bootstrap database/timeout 配置和 `system.databases` 同步；项目数据库支持编辑 MCP alias，Tasks 历史合并展示文档读取与数据库调用。
- 项目数据库选择与 MCP alias 改为单请求原子保存，支持 alias 互换；关系型 Connector 的 names/summary/full 元数据按细节分层并批量加载完整结构。
- 根 Compose 增加固定版本 ClickHouse integration profile；后端补充 Connector、策略、结果预算、管理生命周期、API、MCP、真实 migration 往返和真实 ClickHouse 集成测试，前端补充配置 round-trip、能力和 alias 校验测试。
- 项目数据源授权改为全屏弹窗，移除视口四周留白、圆角与阴影，数据源和数据库选择区使用完整可用高度并保持内部滚动。
- 精简项目数据源授权弹窗顶部，移除重复的项目名称与操作说明，保留“数据源授权”标识和关闭入口，直接展示选择摘要与数据源分类。
- PostgreSQL 数据源同步接入 `pg_database`，过滤模板库并同步当前账号可见、允许连接的数据库；复用既有事务 upsert 和“本次未发现”标记逻辑。本地 PostgreSQL 已从手工维护的 1 个库同步为与 Navicat 一致的 13 个库。
- 数据源编辑密码框新增眼睛按钮；新增禁止缓存的 `POST /api/data-sources/{id}/reveal-password`，列表接口继续过滤口令。新增 PyMySQL 和 MySQL/MariaDB `SHOW DATABASES` 自动同步接口，远端库使用事务 upsert，保留既有库 ID/项目关联并标记本次未发现的旧库。腾讯云 MySQL 已实际同步出当前账号可见的 17 个库。
- 项目“更多操作”新增“管理数据源”：按独立数据源分类选择连接，再多选连接下的数据库；新增 `GET /api/projects/{id}/data-source-options` 与事务型 `PUT /api/projects/{id}/databases`，保留仍选中的既有关联策略，新关联默认只读。数据源详情移除反向关联项目操作，只提示到项目管理配置。
- 新增 migration `20260722_0007` 和 `data_sources.category`；数据源分类与项目类型独立，默认归入“本机电脑”。数据源管理移除顶部大标题说明区，新增“全部数据源 + 动态数据源分类”Tab，并在新增、编辑和连接卡片中展示分类。
- 新增 migration `20260722_0006`，将既有“未分类”项目统一归入“公司项目”，并把数据库、后端及前端的默认项目类型调整为“公司项目”。
- 新增 migration `20260722_0005` 和 `document_projects.project_type`；历史项目默认归入“未分类”，新增和编辑项目支持维护类型。项目管理移除顶部大标题说明区，改为“全部项目 + 动态项目类型”Tab 筛选卡片。
- 新增左侧主导航，将原项目卡片和 MCP 入口归入“项目管理”，新增“数据源管理”页面；支持维护 MySQL、MariaDB、PostgreSQL、SQL Server、SQLite、Oracle、ClickHouse 物理连接、手工库清单及项目与数据库关联。
- 新增 migration `20260722_0004` 和 `data_sources`、`data_source_databases`、`project_databases` 三张表；项目按具体库建立多对多关系，并持久化只读、行数、结果大小和超时策略。连接密码写入 PostgreSQL 但不通过 API 回显，编辑留空时保留原值。
- 调用记录的文档树节点和读取成功的调用列表卡片支持点击查看 Markdown 详情；与普通文档树复用详情 API、加载状态、Markdown 渲染和关闭交互，切换任务或视图时自动关闭旧详情。

### 2026-07-21

- 收敛 Projects 卡片操作区，只保留“更多操作”“查看调用记录”“查看文档树”三个入口；编辑、停用/启用、刷新映射、查看 MCP JSON 和删除移入独立操作弹窗。
- 新增 migration `20260721_0003` 和 `document_projects` 表，持久化稳定项目 ID、名称、AGENTS.md 路径与启停状态；后端启动时恢复配置并为启用项目从磁盘重建内存树。
- 项目 API 和卡片新增编辑、停用/启用、删除能力；编辑或启用先验证完整文档树再写入数据库，路径失效的持久化项目仍保留错误卡片，停用项目不参与 MCP cwd 匹配。
- 默认环境变量项目首次启动时写入项目表；数据库或 migration 暂不可用时保留内存默认项目作为启动降级，不持久化文档树和 Markdown 正文。
- 新增全局“MCP 接入与测试”面板，提供连接信息、Codex TOML、Antigravity JSON 和端到端连接测试四个 Tab；客户端配置由公开 MCP URL 动态生成并支持复制。
- 新增 `GET /api/mcp/integration` 与 `POST /api/mcp/integration/tests`；测试通过 MCP Streamable HTTP Client 真实执行 PostgreSQL、initialize、tools/list、项目匹配、prepare 和入口 read 六阶段，只返回阶段元数据，不暴露连接串或 Markdown 正文。
- 接入测试任务统一使用 `connection-test` Agent，普通项目任务列表默认过滤系统测试记录，`include_system=true` 可显式包含；本次无数据库 migration。
- 调用列表改为按 MCP read call 逐行布局，同一次批量读取的多个文档卡片横向并排，跨批次全局读取顺序角标保持不变。
- 调用记录弹窗新增“文档树 / 调用列表”Tab；树视图复用完整文档层级并按 MCP read call 批次在被读取节点右上角标号，未读取节点继续展示，同一文档支持多个批次角标；原全局读取顺序列表保留。
- 调用记录弹窗改为与文档树一致的全屏网格画布；保留任务切换，并把多次 read 及单次批量 position 展开为全局步骤，在每张文档卡片右上角显示 `1、2、3…` 顺序角标。

### 2026-07-20

- 新增无状态 `read_context_document(task_id, requests)` MCP：一次读取最多 10 个完整 Markdown 或精确 ATX 章节，返回顺序与请求数组一致，并限制在 task 绑定项目的当前内存缓存内。
- 新增 migration `20260720_0002`、`mcp_document_read_calls` 和 `mcp_document_read_items`；read_call_id 由 PostgreSQL identity 生成，单次顺序使用 position，不使用客户端 sequence 或任务锁，数据库不保存正文。
- Projects 卡片新增“查看调用记录”，通过任务列表和读取历史 API 按 read_call_id、position 纵向展示多次调用；同次读取文档不绘制关系线。
- 新增 Streamable HTTP MCP `/mcp` 和无状态 `prepare_task_context(task, cwd, agent_name?)`；按 cwd 最长前缀定位项目并返回完整文档树，不做 Top N 检索、排名或正文返回。
- Markdown 映射刷新时安全解析 YAML Front Matter 的显式 title 和 summary；没有 summary 时省略字段，不从 H1、第一段或文件名兜底生成。
- 引入宿主机 PostgreSQL 任务存储和 Alembic migration `20260720_0001`；`mcp_tasks.id` 作为服务端 task_id，由 identity 自动生成，不使用客户端序号或每任务锁。
- 当前应用使用独立的 `agent_context_router_alembic_version` 版本表，避免覆盖复用数据库中已有的历史 `alembic_version` 链。
- Projects 卡片新增“查看 MCP JSON”，通过 `POST /api/projects/{id}/prepare-preview` 复用同一个 prepare service，并以 JSON 弹层展示完整结果。
- 后端服务端口限制为 `127.0.0.1:49173`，MCP 不接受任意文档路径，只访问已注册项目的当前内存缓存。

### 2026-07-19

- 产品层改为 MCP-only，保留 FastAPI HTTP API 作为 MCP 与 Web 的内部实现；删除旧命令行入口、依赖、脚本和测试。
- MCP 收敛为无状态 `prepare_task_context(task, cwd, project?, agent_name?)` 与 `read_context_document(trace_id, document_id, parent_document_id?)` 两个工具；每次 prepare 独立建链，候选最多 3 份。
- project 默认按 cwd 的最长 root_path 自动识别；read 必须显式传 trace_id，parent_document_id 必须是同链路已读文档，depth 和 duration_ms 由后端生成。
- 前端用 `/tasks` 外层任务列表和 `/tasks/{traceId}` 独立详情替代 Traces 工作台，展示候选、实际阅读、父子链路和 MCP 耗时；移除 Usage、反馈和停止原因运行时。
- Projects 页面增加网页创建项目，Reload Links 改为 Sync Documents；文档页不再展示命令提示。
- 历史数据库字段、usage_cards 表和 migration 暂时保留兼容，不作为当前产品能力暴露。
- 根 AGENTS.md、README、业务/链路文档和 managed 文档改为 MCP-first 按需阅读规则。
- 收紧 MCP-only 边界：坏参数返回工具错误但不终止 stdio 服务；task/cwd/root_path 必须为非空白字符串；项目任务数、任务事件和耗时只统计 MCP prepare/read；MCP 返回值移除冗余渲染字段并压缩文档链接。
- 前端生产构建改在一次性临时副本中运行，避免验证构建覆盖开发服务的 `.next` 缓存、改写源码配置并导致 CSS 静态资源 404。

### 2026-06-27

- 建立 `docs/DEVELOPMENT_OUTLINE.md` 作为代码开发大纲。
- 新建 `docs/development-details/` 目录，用于按类型存放开发细节。
- 根目录 `AGENTS.md` 保留一级索引，开发细节通过大纲按需读取。
- 移除文档切分功能：后端删除 `DocumentChunk`、`document_chunks`、`chunk_id/chunk_count` 和 `chunking.py`；检索改为直接使用 `documents.content_markdown`；前端移除 Chunks 展示；新增 migration `20260627_0003_remove_document_chunks`。
- 补齐任务入口路由：`ctx prepare`、MCP 和 `/api/context/prepare` 支持 `area`、入口路径、入口规则、route hint、source、agent_name；trace 增加对应字段；检索支持按 area 收窄；前端 trace 展示入口元数据和 returned-but-unread；新增 migration `20260627_0004_add_trace_routing_metadata`。
- 收紧受管文档读取：`GET /api/documents/{document_id}` 默认要求 trace/reason 并校验 trace 存在；CLI/MCP 读取会记录 source；显式 `untracked=true` 仅用于管理或调试读取。
- 新增 `ctx project init-index`，用于按 project 和 area 生成短 `AI_CONTEXT_INDEX.md` 入口索引。
- 修正前端 Docker 环境下的后端访问地址：服务端渲染使用 `CONTEXT_ROUTER_INTERNAL_API_URL=http://backend:8000`，浏览器端继续使用 `NEXT_PUBLIC_CONTEXT_ROUTER_API_URL=http://127.0.0.1:49173`。
- 新增文档详情页：Documents 列表文档标题可点击进入 `/documents/{documentId}`，管理端通过 `untracked=true` 查看文档元数据和完整 `content_markdown`。
- 新增项目父子层级：`projects.parent_project_id` 支持大项目聚合子项目；`GET /api/projects` 默认返回顶层项目，`include_children=true` 返回全部项目；项目详情返回 `children`；前端 Projects 页展示大项目，详情页展示子项目列表；新增 migration `20260627_0005_add_project_hierarchy`。
- 重做 Projects 页面卡片：项目卡片内展示聚合 Documents 和 Traces 信息，并提供跳转到相关 Documents/Traces 的两个按钮；`GET /api/projects` 增加 `trace_count`；`GET /api/documents` 和 `GET /api/traces` 的 `project` 筛选支持父项目包含子项目。
- 调整 Projects 卡片布局：桌面端项目卡片使用两列网格，一行可展示两个 Project 卡片，窄屏自动回到单列。
- 收敛受管文档入库边界：清理过细的配置、表结构、manifest、重复清单等文档，将工作区托管文档重置为每个项目的 `AGENTS.md` 和 `AI_CONTEXT_INDEX.md`；后续配置/表结构/源码细节由 AI 按需直接读取项目目录。
- 调整 Projects 卡片按钮交互：Documents/Traces 不再跳转到侧边栏菜单页，而是在 `/projects?panel=...` 中打开覆盖右侧主区域的全页弹窗；弹窗复用 Documents/Traces 页面视图，并提供 Back 返回 Projects。
- 调整 Documents 弹窗内的文档详情交互：从 Projects 的 Documents 弹窗点击文档时，在右侧主区域继续打开嵌套详情弹窗，并支持 Back 返回当前 Documents 列表。
- 优化文档详情弹窗顶部布局：标题、Metadata 和 Read Command 改为紧凑摘要区，减少上方区域高度，让正文内容更早展示。
- 修复文档详情弹窗标题被 Back 工具条遮挡的问题：嵌套详情层工具条改为普通占位布局，不再 sticky 覆盖内容。
- 新增 Documents 文档关系图视图：默认从总索引文档出发，按“如何使用系统”“上下文路由规则”“子项目入口文档”“补充细节文档”展示关联关系；保留 List 视图作为辅助管理入口，Projects 弹窗内文档详情返回时会保留当前视图。
- 调整 Documents 文档关系图为纯文档节点：新增 `usage_guide`、`usage_step`、`routing_guide`、`project_entry_guide` 类型的稳定说明文档，关系图中的分支卡和叶子卡都链接到真实文档详情，不再展示不可点击的说明卡。
- 调整 Documents 关系图层级：从“按类型铺文档”改为“总入口 -> 使用协议 / 任务路由 / 子项目入口 -> 子路由文档”，新增 `area_route` 类型文档用于启动、数据库、前端、后端、业务和排障任务路由；卡片展示下一步数量和推荐 `ctx prepare/read` 命令。
- 补齐 `rob-english-word-workforce` 的总入口和 `AI_CONTEXT_INDEX.md` 受管文档内容：总入口解释 Context Router 使用方式和 `AI_CONTEXT_INDEX.md` 定位；路由入口按 startup/database/frontend/backend/business/debugging 提供 `ctx prepare` 命令模板。
- 优化跨项目功能查询链路：`ctx prepare` 从父项目开始检索时递归包含子项目文档；带 `area` 查询时仍保留 `agent_index`、`routing_index` 等入口文档，避免子服务入口被过滤；图谱卡片命令改为完整换行展示，并补齐 `entrypoint-path/rule`。
- 验证 `rob-english-word-workforce -> word-select-dashboard-web-react` 功能查询：总入口 frontend 查询可召回 web-react、server、word-agent 入口；web-react 路由文档补充 `src/App.tsx`、`src/lib/*Api.ts`、`vite.config.ts` 等功能查询源码路径。
- 优化托管文档检索命中：内容词频按 token 设置上限，避免长入口文档因重复 `ctx prepare` 抢占排序；元数据打分纳入文档 id、source_path、project slug 和当前项目权重；明确 area 查询优先返回对应 `area_route`；中文连续文本增加二字片段匹配，解决“子项目入口文档说明是什么”等中文问法无法命中对应文档的问题。已用 27 个业务场景验证 28 份 active 文档均可命中。
- 文档详情页 Content 区域改为 Markdown 渲染：新增前端 `MarkdownContent` 组件，支持标题、段落、列表、引用、代码块、行内代码、链接和表格；文档正文不再以 raw `<pre>` 展示，页面级验证确认 `.markdown-content` 已渲染标题、列表和代码块。
- 文档独立详情页顶部返回入口改为明确的 `Back` 按钮样式，避免原 `Documents` 文字链接不明显；Projects 弹窗内的嵌套详情仍由外层弹窗工具条提供返回。
- Trace 详情页改为工作流图：按 Task -> Prepare -> Returned Documents -> Read Events -> Feedback 展示一次调用链路，箭头明确指向下一步；每个任务、prepare、返回文档、read 事件和 feedback 节点都可点击查看详情，并保留返回当前 Trace 总览的 Back 入口。
- 优化 Trace 工作流视觉布局：详情页顶部压缩为工具条，默认隐藏空详情卡，流程图改为全宽主视图；节点、元数据和步骤说明整体缩小字号，让调用链图成为页面视觉重点。
- Trace 工作流卡片详情前置展示：点击 Task 卡片时在流程图上方显示“提示词详情”，使用与 Documents 详情一致的 Markdown 渲染方式展示完整用户任务和路由上下文；其他节点详情也改为出现在流程图上方，避免被下方滚动区域遮住。

### 2026-06-28

- 调整 Context Router 调用协议：AI 面向命令改为 `ctx prepare --project <project> [--area <area>]` 和 `ctx read <doc-id>`；`traceId` 与 `reason` 不再要求 AI 手动传入，CLI/MCP/API 内部自动串联或创建读取 trace。
- 同步后端 API、CLI、MCP、前端 Read Command、Documents 关系图和受管说明文档，移除旧的 `--trace`、`--reason` 和必填用户任务占位。
- 调整为 read-first 文档树索引：总入口和 `AI_CONTEXT_INDEX.md` 直接列出下一层文档、用途和 `ctx read <doc-id>` 示例；`ctx prepare` 降级为无法判断 doc-id 时的兜底检索；Documents 关系图卡片命令统一展示 `ctx read <doc-id>`。
- Trace 链路改为适配 read-first 文档树：`ctx read` 事件记录 `parent_document_id`、`depth`、`read_mode=tree_read`、文档标题和项目 slug；CLI/MCP 自动维护当前读取路径并提供 `ctx reset`；前端 TraceFlow 主视图改为 Entry -> Document Path -> Fallback Prepare -> Feedback。
- 收紧 Documents 关系图去重规则：已经挂在“子项目入口”下的 `project_overview` 不再进入“补充说明”链路，避免“子项目概览 -> 其它子项目概览”的重复/误导关系。
- 新增 `rob-english-word-workforce` 第二层数据库连接节点：`rob-english-word-workforce-database-info` 记录 PostgreSQL/Redis 连接信息、只读检查命令和排查起点；前端 Documents 关系图新增 `database_info` 类型，作为不展开第三层的“数据库信息”叶子节点展示。
- 新增 `rob-english-word-workforce` 第二层链路流转节点：`rob-english-word-workforce-flow-overview` 概述用户侧前端、Java 后端、后台 React/Go 服务、Python word-agent、PostgreSQL/Redis 之间的主要流转；前端 Documents 关系图新增 `flow_overview` 类型，作为不展开第三层的“链路流转”叶子节点展示。
- 调整本项目服务管理规范：`docker-compose.yml` 为 `postgres`、`backend`、`frontend` 增加 `restart: unless-stopped`；`docs/STARTUP_GUIDE.md` 和根 `AGENTS.md` 明确本项目只使用当前目录 Docker Compose 启动、重启、自测、测试、lint、build 和 migration。
- 优化覆盖层关闭交互：Projects 弹窗、嵌套文档详情、Document 详情、Trace 详情和 Trace 节点详情中的 `Back` 文案按钮统一改为右上角 `×` 关闭按钮；移除 Projects 弹窗顶部 sticky 工具条，避免滚动时遮挡关系图内容。

### 2026-06-29

- 文档关系改为本地 Markdown 链接驱动：新增 `document_links` 表和 `20260629_0006_add_document_links` migration；后端同步时从带 `doc_id` front matter 的 `docs/*.md` 文档解析本地 `.md` 超链接，生成 `source_document_id -> target_document_id` 关系。
- 新增 `ctx doc sync --project <project> --docs-dir docs --prune`，用于把本地 Markdown 文档和链接关系同步到数据库；数据库从“文档编辑源”调整为“本地文档索引缓存”。
- `GET /api/documents` 和 `GET /api/documents/{document_id}` 增加 `links` 字段，前端 Documents 关系图改为按真实链接关系渲染，不再依赖固定 `doc_type` 路由分类。
- 将 `rob-english-word-workforce` 的入口、子项目总览、数据库信息、链路流转和 7 份项目概览迁移为 `docs/` 下带 front matter 的本地 Markdown 源文件。
- 调整本地文档源位置：`ctx doc sync --docs-dir docs` 的相对路径优先解析为目标项目 `root_path/docs`；Docker Compose 后端只读挂载 `/Users/conchi/workforce:/workspace` 并配置 host/container 路径映射；`rob-english-word-workforce` 文档源移动到 `/Users/conchi/workforce/rob_english_word_workforce/docs`，Context Router 仅扫描并缓存索引关系。
- 调整目标项目文档层级：大项目第一层入口改为目标项目根 `AGENTS.md`，第二层保留在 `docs/*.md`，第三层目录按所属第二层 `doc_id` 命名，例如 `docs/rob-english-word-workforce-subprojects-overview/*.md`；同步 `--docs-dir .` 时只读取根 `AGENTS.md` 和 `docs/**`，避免误扫子项目目录。
- Projects 卡片新增 `Reload Links` 操作：前端通过同源 Next route 代理到后端 `/api/projects/{slug}/documents/sync-local`，按 `docs_dir="."` 和 `prune=true` 重载本地 Markdown 文档及 `document_links` 链路缓存，成功后刷新项目统计。

### 2026-06-30

- 文档详情和检索正文来源改为实时读取本地 Markdown：数据库继续保存 `doc_id`、`source_path` 和 `document_links` 作为索引缓存；`GET /api/documents/{document_id}` 与检索打分优先根据项目 `root_path` 读取本地文件并剥离 front matter，根目录不可访问的旧文档再回退数据库旧内容。

### 2026-07-03

- 新增 Usage 卡片功能：增加 `usage_cards` 表和 `20260703_0007_add_usage_cards` migration；后端提供 `/api/usage/cards` CRUD 接口并首次访问初始化内置 `ctx / SESSION_ID 使用说明` 卡片；前端新增 Usage 菜单、卡片网格、Markdown 弹窗预览和编辑能力。
