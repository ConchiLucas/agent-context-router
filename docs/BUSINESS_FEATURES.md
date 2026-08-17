# 业务功能说明

## 产品目标

让开发者先把本机代码根目录注册为工作空间，再在工作空间内分别配置一个或多个前端/后端项目的源码相对路径和文档入口相对路径，并把工作空间级文档、全部项目文档和只读数据库授权提供给本地 Codex、Antigravity 等 MCP 客户端。真实 Workspace 根 `AGENTS.md` 定义工作空间文档树的显式层级；各项目位于 `docs/` 层级下的 `AGENTS.md` 递归文档独立加入 Workspace 搜索和按 ID 读取范围。缺少真实根时才使用直接列出项目入口的合成根。数据库以 Workspace 内唯一别名暴露渐进 Schema 搜索和有界只读查询，不把连接信息交给 Agent。

## 工作空间与项目

- 工作空间是顶层管理和聚合边界。数据库保存稳定 ID、名称、类型和兼容 `root_path`；当前电脑的主目录和卡片显示由项目内 `.context-router/workspaces.local.yaml` 决定。
- 一个工作空间可以没有项目，也可以配置根项目和多个嵌套项目。项目属于且只属于一个工作空间，保存项目名称、`frontend/backend` 类型、源码 `relative_path` 和文档入口 `document_relative_path`；源码根项目使用 `.`，Workspace 和 Project 都没有启停状态。
- 源码根由 `workspace.root_path / project.relative_path` 定位，项目入口由 `workspace.root_path / project.document_relative_path` 定位；兼容 `agents_path` 只保存后者的绝对路径镜像。两类相对路径都不能是绝对路径，不能使用 `~`、反斜杠或 `..`，解析后也不能通过软链接越出工作空间；同一工作空间内两类路径分别唯一。
- 项目源码路径和文档入口路径由本机 AI 或运维通过受校验 API 显式配置，不自动扫描目录或猜测哪些子目录是项目。新项目文档入口必须位于 `docs/` 下并以 `AGENTS.md` 结尾，推荐使用 `docs/{frontend|backend}/{项目目录名}/AGENTS.md`。
- Workspace 根目录存在 `AGENTS.md` 时自动作为工作空间级文档入口；没有该文件时保留合成工作空间根。这个约定不新增配置字段，也不把工作空间文档伪装成 frontend/backend Project。
- 工作空间配置以及项目 ID、归属、类型、源码路径、文档入口路径和推导后的兼容 `agents_path` 持久化到 PostgreSQL，后端重启后自动恢复。
- 本机映射项包含 `visible`、`main_path` 和 `document_reader_paths`。隐藏项不显示卡片也不参与本机 cwd 路由；共享目录只可读取主目录文档，不能使用数据库和部署工具。
- 浏览器工作台允许重载本机映射、刷新文档缓存，以及在明确确认后全量覆盖文档与部署文件；其他配置继续由受校验的本机 AI/运维 API 维护。
- Context Router 自身的使用说明由“系统文档”菜单统一展示，包括当前 MCP `tools/list` 的中文说明，不进入业务工作空间的 `AGENTS.md`，也不随 prepare 返回。
- AI/运维新增或编辑项目时先验证并重建完整文档树，成功后才更新数据库和当前内存状态；工作空间记录存在即参与目录匹配，不提供总启停开关。
- 持久化路径失效时项目卡片仍保留并显示错误；路径修复由 AI/运维完成，修复后可从 Workspace 卡片触发全量刷新。
- migration `20260726_0013` 会为每个旧项目建立一个同 ID 工作空间，工作空间根目录取旧 `AGENTS.md` 的父目录，旧项目作为 `relative_path='.'` 的根项目；`20260726_0014` 为项目增加 `project_kind`（旧记录默认 `backend`）并删除 Project enabled；`20260726_0015` 增加 Workspace 根文档派生搜索索引；`20260727_0016` 增加 `document_relative_path` 并从旧 `agents_path` 回填，迁移本身不移动磁盘文档。原项目 ID、数据库授权和调用历史不变。

## 文档映射

Workspace 和 Project 的入口都固定命名为 `AGENTS.md`；Workspace 入口仍位于根目录，新的 Project 入口集中到 `docs/` 分层目录。每个参与递归的文档使用固定格式：

```markdown
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 功能说明文字 | `./任意深度/文档.md` |
```

解析规则：

1. 只读取标题为 `## 下级文档` 的第一个标准两列表格。
2. 相对路径以当前文档目录为基准。
3. 路径必须以 `./` 开头，并保持在当前文档目录范围内。
4. 目标必须是 Markdown 文件。
5. 没有“下级文档”表格时，该文档是叶子节点。
6. 正文普通链接不参与层级映射。
7. 文件缺失、格式错误和循环引用在树节点上显示错误。
8. 存在真实 Workspace 根 `AGENTS.md` 时，不自动把未声明的 Project 根入口追加到工作空间树；这些项目文档仍参与 Workspace 搜索并可按搜索结果 ID 读取。
9. Workspace 根 `AGENTS.md` 不存在时，合成根直接列出当前配置的 Project 根入口。

参与 MCP 全局认知的文档可以在文件开头显式声明：

```markdown
---
title: 启动与开发规范
summary: 说明项目前后端启动、测试、构建和 migration 的统一方式。
---
```

title 和 summary 只读取 Front Matter，不从正文兜底生成；没有 summary 的普通文档仍保留在树中。

## 内存缓存与刷新

- 注册 Workspace 时读取可选的根 `AGENTS.md`；首次添加项目时从独立的 `document_relative_path` 立即递归读取该项目全部文档。
- 缓存包含完整树和每个文件的 Markdown 原文。
- PostgreSQL 只保存从当前缓存版本生成的规范化检索分块和索引状态；Markdown 原文仍以磁盘文件为唯一真源。
- 树接口不返回正文，详情接口按节点 ID 从内存读取正文。
- 手动刷新以 Workspace 为单位，在临时区重建可选根入口和全部子项目，不在旧缓存上合并；启动恢复和工作空间刷新成功时同步重建工作空间级及相应项目的词法索引。
- 成功刷新后，已删除的节点和旧正文不会残留。
- 刷新会完成全部 Project 的预校验并记录每个失败项目；任一 Workspace/Project 入口构建失败时保留上一份完整工作空间缓存，一次响应汇总全部入口问题。
- Workspace 根文档和 Project 文档分别使用独立派生索引；搜索必须命中与当前缓存相同的 index_version。索引缺失、构建失败或版本落后时返回明确的 index-not-ready 错误，不扫描内存正文兜底。

## 页面

- 首页左侧主导航为“工作空间 / 数据源 / 调用链路 / 系统文档”。工作空间页顶部使用“全部工作空间 / 动态工作空间类型”Tab 筛选工作空间卡片。
- 左侧“系统文档”按当前 MCP `tools/list` 为每个工具提供独立的只读源码/树形视图，页面使用简洁中文介绍但不修改 AI 客户端收到的原始英文工具描述；页面同时允许搜索已有统一 JSON 使用说明、切换树形/源码和保存正文，不提供新建、删除、key、顺序、prepare 策略、启用、版本或发布状态。
- 页面能力收敛为查看、筛选和复制，以及不会修改配置的连接测试、密码按需查看、Workspace 刷新、MCP 接入/测试、文档树、调用历史和运行记录查看。
- 工作空间卡片展示本机主目录、共享文档目录数量、项目数量、数据源/数据库授权汇总和更新时间；页面顶部可在编辑 YAML 后“重载本机映射”。右上角“刷新映射”只重建文档缓存与派生搜索索引。
- 工作空间详情提供“前端项目 / 后端项目 / 数据源汇总”三个 Tab；前两个 Tab 按 `project_kind` 展示根项目和嵌套项目卡片，以及项目名称、类型、源码相对路径和文档入口相对路径。
- 工作空间详情工具栏提供“文档与部署文件 / MCP 接入 / 环境详情 / 查看调用记录 / 查看文档树 / 查看 MCP JSON”。“文档与部署文件”只有“从数据库恢复到主目录”和“用主目录覆盖数据库”两种全量操作，每次只做一次删除确认，不展示版本、差异或冲突流转。
- 项目卡片只展示项目元数据并提供必要的查看入口：后端项目可查看当前数据库授权，前端和后端项目都可查看运行配置。运行配置全屏页按快速/完整更新读取部署文件，并展示 Runtime Runner 历史运行、状态和有界日志，不提供文件增删改、保存、物化或执行操作。
- 文档树使用全屏可拖动画布和矩形节点，从上到下展示层级。每个总览或子树详情视图都以单个文档为第一层，其全部直接子文档作为第二层横向平铺；从第三层开始按父文档独立判断，直接子文档不超过 4 个时继续递归，超过 4 个时每行最多显示 4 个并停止该分支继续内联后代。被停止分支中仍有下级文档的卡片显示下级数量入口，叶子卡片不显示；点击卡片主体查看 Markdown，点击下级入口以该卡片为新根进入子树详情，并通过面包屑逐级返回。不同分支独立判断，一条分支换行不会阻止其他未超限分支继续向下展示。
- 点击节点后，通过独立详情抽屉展示 Markdown 标题、表格、列表、代码块和引用。
- Markdown 渲染不执行原始 HTML 或脚本。
- Workspace 工具栏支持查看 MCP JSON；预览与 MCP prepare 使用同一精简返回模型，只包含 task_id、access、必要 warning 和三层文档投影，不内联数据库别名、环境 JSON 或凭据。
- Workspace 工具栏支持查看 MCP 调用记录，并在同一个全屏网格画布中切换“文档树”和“调用列表”：任务选择器列出该工作空间内至少产生过 read call 或数据库调用的 task；历史文档树只保留该任务实际调用过的文档及其从工作空间根开始的完整父级链路，隐藏未调用的旁支和后代，并在可见的已读取节点右上角标记文档读取批次。历史文档已不在当前树中时引导切换调用列表；未进入显式树的项目文档读取也继续保留在调用列表中。调用列表按时间合并文档读取和数据库调用，同一次批量读取的文档横向排在同一行，读取成功的文档仍可打开 Markdown 详情。
- 左侧主导航提供独立“调用链路”页面，统一按任务查看 Context Router MCP 工具调用。页面支持任务搜索、Agent、十个当前工具、三个已下线工具的历史记录和状态筛选，只在“调用树 / 调用列表”之间切换；不加载完整项目文档树，也不在这里打开 Markdown。
- 调用树以任务为根节点，按服务端稳定顺序展示 MCP 工具调用。一次 `read_context_document` 仍是一个工具调用节点，其批量读取的多个文档作为同一节点的横向产物；普通连续调用只表达顺序，只有显式父调用时才表达因果关系。任务列表和详情同时展示“完整 / 运行中 / 可能不完整”，prepare 记录缺失、历史恢复、服务重启中断或明细失联会显示明确提示。
- 调用链路页的文档工具节点只显示状态、耗时和读取规模，不提供完整出入参详情。数据库工具节点可按需打开全屏详情页，在“请求参数 / 响应结果”之间切换并复制当前内容。SQL 单独显示，历史未采集、过期、采集失败和快照截断都有明确状态。
- 工作空间详情工具栏提供“MCP 接入”面板，集中展示服务地址、工具能力、Codex/Antigravity 配置模板，并针对当前 Workspace 执行连接测试；客户端配置由后端按公开 MCP URL 生成，可直接复制。
- 数据源页按全局物理连接查看 MySQL、MariaDB、PostgreSQL、SQL Server、SQLite、Oracle 和 ClickHouse；数据源分类与工作空间类型相互独立，可使用“自己服务器、公司内网服务器、本机电脑”等分类。
- 数据源页顶部使用“全部数据源 / 动态数据源分类”Tab 筛选连接卡片；“查看连接”详情展示连接参数、Engine 能力和数据库清单，不提供连接或数据库清单的新增、编辑、删除与同步。
- 数据源密码默认不随列表接口下发；用户点击密码框右侧眼睛后，通过独立 no-store 接口按需读取当前连接的明文密码，再次点击恢复隐藏。连接测试保留，只返回状态、耗时和短错误码。
- MySQL/MariaDB 数据源通过 `SHOW DATABASES`、PostgreSQL 通过 `pg_database`、ClickHouse 通过 `system.databases` 发现当前账号可见的全部库；同步仍由 AI/运维调用受校验 API，保留既有库 ID 和项目关联，新增远端库，远端不再可见的旧库只标记为不可用，系统库单独标识。
- 数据源页面从后端能力接口读取真实能力。MySQL、MariaDB、PostgreSQL 和 ClickHouse 当前支持连接测试、数据库同步、对象搜索和只读查询；SQL Server、SQLite、Oracle 只保留可查看、可由 AI/运维维护的连接配置，不会被标记为 MCP 可查询。
- ClickHouse 连接可配置 HTTP/HTTPS、证书校验、启动数据库、连接超时和读写超时。后端运行在 Docker 中时，访问宿主机服务使用 `host.docker.internal`；连接测试只返回状态、耗时和短错误码，不返回密码、DSN 或驱动堆栈。
- 后端项目的“数据源详情”只展示当前数据库授权、稳定别名和查询策略，不提供选择或保存。AI/运维通过既有批量 API 维护时，仍在一次事务内整批替换该项目的数据库关联，未改动的既有关联继续保留原查询策略。
- 每个项目数据库关联拥有稳定的 `mcp_alias`，格式为 `^[a-z][a-z0-9_-]{0,63}$`；唯一性在整个 Workspace 内大小写无关校验，两个不同项目不能使用同一别名。Agent 只使用 `read_task_context` 返回的别名；数据源 ID、远端库名、Host、账号和密码不会进入 MCP 参数。
- AI/运维批量维护项目数据库时，把数据库选择和全部 `mcp_alias` 作为一次事务保存；别名 A/B 互换不会经过冲突的中间状态，请求失败也不会留下部分更新，Repository 和数据库唯一索引都会校验其他子项目已经占用的别名。
- 项目数据库关联默认只读、最多返回 1000 行、结果上限 2 MB、查询超时 15 秒；这些策略持久化后由服务端和全局硬上限共同收紧。数据库不可用、系统库、非只读关联、缺少 MCP 别名以及没有 Connector 的 Engine 都不会出现在 `read_task_context` 的数据库清单中。
- 数据库授权归属仍是项目：物理连接和库清单作为全局数据源配置保存，`project_databases` 只关联具体项目。新 Workspace task 会汇总并使用所有子项目的有效授权，`read_task_context` 的每条数据库摘要同时返回所属项目 ID、名称和 `project_kind`；“数据源汇总”只聚合展示，不复制授权或查询策略。
- Workspace 可选配置 TEST/UAT 环境映射。环境详情按项目和稳定逻辑别名并列展示两个环境的物理数据库及问题状态，但不提供自动匹配、手工修正、保存或全局环境切换；这些配置变更由 AI/运维通过受校验 API 完成。显式 prepare 的任务级环境选择不修改 Workspace 当前环境。
- 环境映射复用已有 `project_databases` 的只读策略，不复制连接口令。`prepare_task_context(environment='test'|'uat')` 可为单个 task 显式固化环境并记录 `task_explicit`；省略参数则使用 Workspace 当前环境并记录 `workspace_default`。`read_task_context` 返回的数据库摘要和后续工具都按 task 环境解析。
- 保存映射、保存通用 JSON 或切换 Workspace 当前环境都会递增共享 revision；两种选择模式的旧 task 都会在数据库工具调用时返回 `environment_changed` 并要求重新 prepare。未配置环境选择器的单环境 Workspace 在省略参数时保持原有数据库授权行为，显式传参返回 `environment_not_configured`。
- “环境详情”面板另有通用 JSON 页签，以只读格式分别展示 TEST/UAT JSON 对象，不为 MQ、Redis、MinIO、ES 或未来组件预设字段。JSON 可以在没有数据库映射时独立建立环境选择器，首次由 AI/运维保存时默认当前环境为 UAT。两份 JSON 合计最多 256 KiB、最多嵌套 20 层，超出 JavaScript 安全整数范围的值应改用字符串。
- task 所选环境的 JSON 只在显式调用 `read_task_context` 请求 `environment` 时返回给可信本机 MCP 调用方。可按明确业务需要保存地址及密码、Token、AccessKey 等访问凭据，但内容以明文 JSONB 保存在本地；严禁把实际值写入日志、开发文档、链路摘要或示例输出。
- Workspace 可另行配置 `default/test/uat` Nacos 连接和组件抽取规则。prepare 不传环境时中间件固定使用 `default/local`，显式传 `test/uat` 时使用同名配置档；这项选择不受 Workspace 当前默认环境影响，也不改变数据库环境映射语义。本机 `read_middleware_context` 默认返回密码、Token、SecretKey 等明文字段，调用方可显式传 `reveal_secrets=false` 获取脱敏视图；Nacos 地址、命名空间、dataId 和字段路径均由服务端配置决定，MCP 调用方不能临时改写。
- prepare 的 `access` 对完整 Workspace task 显式包含 `middleware`。涉及 Nacos 管理的中间件实时连接或诊断时，`read_middleware_context` 是权威入口；`read_task_context` 的通用环境 JSON 只作为兼容配置，不替代实时 Nacos。本机授权任务可在当前回答中返回并使用明文凭据建立诊断连接，但不得把实际值写入源码、Markdown、持久化日志、无关工具参数或提交记录。
- 浏览器 API 客户端和后端 `BrowserReadOnlyMiddleware` 双重限制配置写操作。除既有诊断/预览外，工作空间页面只额外允许重载本机映射和双向共享文件全量覆盖；旧 deploy 预览/摘要接口不再允许浏览器调用。其他方法返回 `405 management_read_only`。

## Workspace 运行编排

- 运行边界是整个 Workspace。用户说“启动”“启动项目”或“启动服务”时，`start_workspace` 始终排入 Workspace 唯一的完整启动脚本，由脚本决定并启动该目录下的全部项目，不在 MCP 层提供单项目启动分支。
- 代码修改完成后，Codex 按根 `AGENTS.md` 的约定调用一次 `apply_workspace_changes(task_id, changed_files)`。服务端用 Workspace 相对路径做最长 Project 前缀匹配：项目内文件选择该项目的快速或完整更新；Workspace 级文件、`.env.local`、无法唯一归属的文件或跨项目改动统一选择完整更新。
- `get_workspace_operation(operation_id)` 只查询已排队操作，服务端从操作记录解析并校验任务归属，返回操作、步骤、终态和有界日志，不在查询时触发执行。Project 级兼容工具已经下线，单项目更新也统一由 `apply_workspace_changes` 按变更路径路由。
- Context Router 是控制面：PostgreSQL 保存 Workspace 启动文件、Project 快速/完整更新文件、项目顺序、路径策略和异步操作状态；它不在后端容器内直接执行目标仓库脚本。
- 目标仓库 `deploy/context-router/` 是运行配置唯一事实源：根 `manifest.yaml` 和 `workspace/start/` 描述 Workspace，Project 根 `deploy/context-router/fast|full/` 描述两种更新模式。同步器只读取固定目录，拒绝软链接、越界路径、非 UTF-8、敏感文件、缺失或不可执行的 `deploy.sh`、非法 YAML 和不完整 Project 集合。
- 页面使用 `POST /api/workspaces/{id}/shared-files/publish|restore` 完成主目录与数据库间的全量覆盖；publish 在一个 PostgreSQL 事务中同时替换源文件副本及 Workspace/Project 运行配置。旧 deploy 预览接口只保留给本机 AI/运维兼容调用，不进入浏览器交互。
- Project 运行配置保存边界会对非空 `.yml/.yaml` 文件做 YAML 语法解析；失败只返回文件、行和列，不回显内容或覆盖旧记录。Compose 语义继续由目标脚本预检。采用统一机器配置的 Workspace 应让各 Project 的 `fast/deploy.sh` 成为无凭据包装器，由目标仓库同一个根部署入口加载 `.env.local` 并仅调度命中的 Project；这不改变 `start_workspace` 始终全量启动的 MCP 边界。
- Host Runtime Runner 是执行面：由用户在宿主机手动启动，使用仅本机可读 Token 向回环控制面注册、心跳和领取操作，逐步物化不可变快照，校验清单、哈希、路径与软链接边界后，只执行快照根固定的 `deploy.sh`。步骤串行运行，首个失败后后续步骤标记 skipped，不自动清理或修复目标环境。
- 目标 Workspace 根 `.env.local` 是唯一的机器差异入口，保存当前电脑真实的数据库、Redis、MinIO 等连接信息，并由目标仓库脚本自行读取。该文件不进入 Git、不写入 Context Router 数据库、不复制到运行快照，也不得进入日志；换电脑只初始化这一份文件。
- Context Router 和 Host Runner 不配置 Docker/launchd 开机自启。用户需要编排能力时，在本仓库手动执行本地栈启动脚本；目标 Workspace 的首次启动和后续全量启动使用同一个 `start_workspace` 协议。

## MCP

- MCP 固定提供十个工具：七个上下文、只读数据库与中间件工具，以及三个 Workspace 运行编排工具 `apply_workspace_changes`、`start_workspace`、`get_workspace_operation`。数据源或中间件记录增删不会改变 `tools/list`。
- 服务端先在全部工作空间根目录中按 cwd 最长前缀确定 Workspace，再按源码 `relative_path` 计算最深匹配 Project 作为 `active_project` 快照；docs 文档入口目录不参与活动项目归属。活动项目只帮助说明 Codex 当前开发位置，不限制文档、搜索、read 或数据库授权范围。
- prepare 不按 task 内容搜索或排名，也不返回 Markdown 正文；它只返回 task_id、可用能力、必要 warning，以及节点仅含 `document_id`、`summary`、`children` 的确定性三层投影。存在真实 Workspace 根 `AGENTS.md` 时固定从它开始；缺少真实根时，才从 cwd 命中的 Project 入口或合成根开始。未返回的深层文档和其他 Project 文档仍可由 Workspace 范围的 `search_context_documents` 定位并按结果 ID 读取。数据库别名和环境 JSON 由 `read_task_context` 按需返回。
- `prepare_task_context` 的可选 `environment` 只接受 `test/uat`。显式值是 task 局部选择，不执行 Workspace 切换；省略时读取 Workspace 当前环境。配置选择器时，返回的 `database_environment.selection` 分别为 `task_explicit` 或 `workspace_default`；未配置选择器时只能省略该参数。
- 每次成功调用 prepare 都由 PostgreSQL 生成独立 task_id。
- 新 task 保存 `scope='workspace'`、稳定的 workspace_id/workspace_key/name、可选 active_project 快照，以及可选 `database_environment`、共享 revision 和 `database_environment_selection`。活动项目删除或同路径重建不会改变 task 的历史展示身份，但后续工具授权始终重新校验 task 绑定 Workspace 的当前状态。
- `20260726_0014` 之前的 task 保持 `scope='project'`：read/search 继续按稳定 project_id，无法回填时按 project_key 兼容解析；migration 同时回填 Workspace 和活动项目字段，使旧调用可出现在工作空间调用记录中。Workspace 一旦启用环境选择器，旧 Project task 的数据库调用会返回 `environment_changed`，必须重新 prepare，避免绕过环境 revision。
- Context Router 收到的每次 `tools/call` 都统一记录为任务下的 MCP 工具调用，包括 Server、工具名、服务端顺序、采集来源、状态、开始/结束时间、耗时、错误码和脱敏摘要。prepare 成功创建 task_id 后补记为该任务的第一个调用；后续工具在执行前创建运行中记录。
- read 必须携带当前任务的 task_id，一次支持 1 到 10 个文档或精确章节，并保持请求数组顺序。
- `search_context_documents` 必须携带当前任务的 task_id。Workspace task 会搜索可选的 Workspace 根文档和全部 Project 文档，再按文档 ID 聚合排序；工作空间入口与 Project 重复映射时工作空间入口优先，嵌套项目之间的重复文档归最深项目所有。旧 Project task 继续只搜索原项目。输入为 query 和最多 50 的 limit；输出包含文档 ID、Workspace 相对路径、标题、概要、相关度、命中章节和命中原因，不返回正文或摘录。树较大或目标不明确时先 search，再按结果调用 read。
- 第一版文档搜索使用 PostgreSQL `to_tsvector('simple', ...)`/`websearch_to_tsquery('simple', ...)` 与 `pg_trgm` 组合评分，覆盖路径、标题、概要、章节和正文；中文短词保留精确子串匹配，不使用向量数据库。
- 每次 read 由 PostgreSQL 生成 read_call_id；客户端不传 sequence，服务端不使用任务锁。
- `mcp_document_read_calls` 和 `mcp_database_calls` 继续保存工具专属客观明细，并通过 `tool_call_id` 关联统一调用；旧历史在 migration 中恢复为 `legacy` 调用，不伪造历史 prepare 节点或缺失耗时。
- 后端启动时把上次进程遗留的内部 `running` 调用标记为 `error/server_restarted`；链路 API 会按 prepare 是否存在、运行中、历史、重启中断和失联明细计算完整性。普通无内部调用 task 仍可作为“可能不完整”记录查看，管理端预览和接入测试任务不进入链路列表。
- 新 task 的数据库调用固定经过 `task_id -> task 绑定 Workspace -> Workspace 唯一 mcp_alias -> 所属项目当前授权与连接策略 -> Connector`，因此可以使用任一子项目在 `read_task_context` 中返回的别名；旧 `scope='project'` task 继续走原项目 alias 兼容链路。客户端不能直接提交项目、连接或数据库内部参数。
- `search_database_objects` 支持 schema、table、view、column、index，并以 `names -> summary -> full` 渐进增加细节。客户端可传 glob pattern、schema、table 和 limit；服务端还会按细节级别、结果字节数和项目策略截断。
- `execute_database_query` 只接受一条可安全解析的只读 SQL。服务端拒绝写操作、多语句、跨库访问、外部表函数以及文件/网络访问函数，并同时施加行数、结果字节数、超时和数据库侧只读约束。返回值明确携带截断状态，不把截断结果伪装成完整结果。
- Connector 按当前数据源配置和数据库版本延迟创建并有界缓存；prepare、文档 read 和 `/health` 不依赖业务数据库在线。
- 数据库保存文档读取顺序和数据库调用客观审计元数据；`mcp_database_calls` 仍只保存 SQL SHA-256 和结果规模，不保存完整 SQL 或结果集。数据库 payload 会自动写入独立的 `mcp_database_tool_payloads`，仅对白名单数据库工具保存实际请求和已经过服务端预算处理的最终 MCP 响应，默认 7 天后清除 JSON。
- 工具调用摘要按工具白名单生成：文档只记录 ID、章节和数量，普通 Trace 结果只保存规模信息；密码、Token、Markdown 正文、数据源连接参数和 Connector 原始结果不会进入链路表或 payload。payload 采集失败只影响详情可见性，不影响 Codex 当前 MCP 调用。
- 接入面板的端到端测试接收 `workspace_id`，真实执行 PostgreSQL 检查、MCP initialize、tools/list、Workspace cwd 匹配、prepare、search 和入口文档 read；页面只接收任务号、调用号、阶段耗时和正文字符数，不返回 Markdown 正文。
- 接入面板测试不会执行工作空间业务数据库查询；真实 ClickHouse 查询由独立 Docker Compose integration profile 验证。
- 接入测试使用 `agent_name=connection-test` 创建系统任务，普通调用记录默认隐藏，可通过任务列表接口的 `include_system=true` 显式查看。

## 非目标

- 不实时监听文件变动。
- 不自动扫描工作空间目录来注册项目；项目相对路径由用户显式配置。
- 不把文档树或 Markdown 原文作为数据库真源；它们始终从本地磁盘重建。数据库仅持久化可随时重建的规范化检索分块。
- 除固定的 Workspace 根入口和各 Project 配置的 `document_relative_path` 外，不扫描没有被“下级文档”表格引用的 Markdown。
- 不使用大模型解析文档层级。
- 不自动修改 Codex 或 Antigravity 的本地配置，也不负责重启客户端。
- 当前接入面板不处理远程 HTTPS、鉴权和 Skill 安装。
- 文档检索不越出 task 绑定的 Workspace（旧 `scope='project'` task 不越出原项目）、不返回完整正文，也不提供向量或混合召回。
- 调用链路页只记录客户端实际发送到 Context Router `/mcp` 的十个当前工具调用，并保留三个已下线工具的历史记录。中间件读取只保存组件数量、明文开关和警告数量，不保存 Nacos 响应或连接凭据。客户端直连 GitHub、浏览器等其他 MCP Server 的调用不记录；本产品不连接或代理外部 MCP，不提供外部调用上报，也不建设跨 Server Trace。
- 不提供数据库写入、DDL、DBA 运维、跨数据库联邦查询或任意外部表函数。
