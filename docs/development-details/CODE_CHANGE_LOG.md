# 代码变更记录

本文件用于记录跨模块、数据结构、接口 contract、工程约定等重要代码变更。

## 记录规则

- 按日期追加记录。
- 只记录代码层面的开发信息，不记录普通聊天。
- 简要结论可同步到 `../DEVELOPMENT_OUTLINE.md`。
- 如果内容影响启动、数据库、业务功能或链路流转，需要同步更新对应文档。

## 记录

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
