# 架构决策记录

本文件记录会影响后续开发方式的技术决策和取舍。

## 记录规则

- 记录决策背景、最终选择和影响范围。
- 不记录普通聊天或临时讨论。

## 记录

### 2026-07-30

- 环境切换采用“稳定逻辑别名 + 两个物理目标”的显式映射，不根据运行时数据库名称临时改写。自动匹配仅作为页面建议，规则是去掉 `test_`/`uat_` 后同后缀；最终映射必须由用户保存并由后端校验目标属于同一 Workspace 和 Project 的既有授权。
- `project_database_environment_targets` 引用 `project_databases`，因此环境层不复制数据源连接、密码和查询限制。映射保存与环境切换都在事务中递增 Workspace revision。
- prepare 固化 `database_environment + database_environment_revision + database_environment_selection`。省略可选 `environment` 参数时记录 `workspace_default`；显式 `test/uat` 时记录 `task_explicit`，只影响该 task，不修改 Workspace 当前环境。`workspace_default` 还要求调用时当前环境未变；`task_explicit` 可以与当前环境不同，但两者都要求选择器存在且共享 revision 一致。revision 不一致时 fail closed 返回 `environment_changed`。
- 通用环境差异采用两份有界 JSON 对象，不为每一种中间件增加列或代码分支。JSON 与数据库映射共用环境选择器和 revision，但不要求映射存在；首次保存默认 UAT。没有映射记录时原有 Workspace alias 保持可用，存在映射记录后才进入严格的环境目标解析。可按明确业务需要保存地址和访问凭据，但内容以明文 JSONB 保存在本地；task 所选环境的 `environment_config` 只供可信本机 MCP 调用方和本机管理预览使用，严禁进入日志、开发文档、链路摘要或示例输出。
- 环境映射是 Workspace 可选能力。没有配置选择器的单环境 Workspace 在省略 prepare 的 `environment` 时继续使用原有 Workspace alias 链路，显式传参返回 `environment_not_configured`，避免 migration 后改变既有项目行为。当前 migration head 为 `20260730_0022`；`0022` 删除 Workspace、数据源、项目数据库授权和环境配置的 `enabled` 字段，记录存在即生效。

### 2026-07-27

- Project 的源码目录与文档入口正式解耦：`relative_path` 只表示源码根和 cwd 活动项目匹配范围，新增 `document_relative_path` 表示 Workspace 内的 Markdown 入口；兼容 `agents_path` 继续保存后者的绝对路径镜像。
- 新建或编辑 Workspace Project 时，文档入口必须位于 `docs/` 下并以 `AGENTS.md` 结尾，推荐目录为 `docs/{frontend|backend}/{项目目录名}/AGENTS.md`。migration `20260727_0016` 只从旧 `agents_path` 回填新字段，不擅自移动宿主机文件；各工作空间在文件准备完成后独立迁移。
- ProjectRegistry 同时保存解析后的源码根和文档入口。Workspace 仍按根目录最长前缀路由，`active_project` 改为按源码根最长前缀选择；将入口集中到 docs 不会改变数据库授权归属或 Codex 当前开发项目。
- Workspace 刷新继续采用全量原子替换，但预构建阶段不再遇到首个坏项目就退出，而是遍历全部 Project、把错误写回对应卡片并一次性返回完整问题清单；任一失败时旧缓存仍保持不变。
- 当前 migration head 为 `20260727_0016`。旧 `scope='project'` task、项目 ID、数据库授权和调用历史不变。

### 2026-07-26

- 顶层管理实体和 Codex 运行时上下文边界统一为 Workspace。Workspace 保存唯一绝对根目录和总启停状态；Project 必须归属一个 Workspace，只保存名称、`frontend/backend` 类型和工作空间内唯一的 `relative_path`，没有独立 enabled。根项目用 `.`，`AGENTS.md` 入口由两者确定性推导；当前不自动扫描目录注册项目。
- cwd 路由在全部 Workspace 根目录中选择最长前缀，工作空间内最深 Project 只记录为 `active_project` 元数据。prepare、search、read、调用记录、文档树、刷新和 MCP JSON 都以 Workspace 为边界；活动项目不收窄文档或数据库范围。
- Workspace 根目录固定自动探测可选 `AGENTS.md`，不新增路径配置字段；缺失时继续使用合成入口。ProjectRegistry 分别保留工作空间级及各 Project 的 DocumentCache 和搜索索引，再构建 Workspace 聚合缓存。Workspace 刷新先构建根入口和全部子项目，任一文档构建失败时保留整份旧映射；重复文档由 Workspace 入口优先，Project 之间按最深所有者去重。
- 物理数据源和数据库清单继续全局维护，授权记录仍由 `project_databases` 绑定具体 Project；Workspace task 汇总使用所有子项目当前有效的授权。`mcp_alias` 唯一约束提升到 Workspace，`read_task_context` 的数据库摘要携带所属项目 ID、名称和类型，数据源汇总视图不复制授权或策略。
- 新 prepare 写入 `scope='workspace'`、稳定 Workspace 快照和可选活动项目快照；read/search/database 每次按 Workspace 当前状态重新校验。migration 前的 task 保持 `scope='project'` 和原 project_id/project_key 权限范围，同时回填 Workspace/活动项目字段供工作空间调用记录查询。
- migration `20260726_0013` 先采用兼容式一对一回填：每个旧 Project 生成同 ID Workspace，旧入口父目录成为 `root_path`，Project 设为 `relative_path='.'`；`20260726_0014` 再新增 `project_kind`、删除 Project enabled、把数据库 alias 提升到 Workspace 唯一，并增加 Workspace task 快照；`20260726_0015` 为 Workspace 根文档新增独立派生搜索索引。旧 `agents_path/project_type` 暂时双写兼容，当前 migration head 为 `20260726_0015`。

### 2026-07-25

- 本节记录的是 0014 前的 Project task 阶段；其中“task 绑定项目”“项目卡片调用记录”和项目级刷新已经由 2026-07-26 的 Workspace scope 决策取代，搜索算法、索引版本与 payload 预算决策仍有效。
- MCP 工具集合扩展为五个固定工具，在 prepare 与 read 之间增加 `search_context_documents(task_id, query, limit)`。搜索范围严格绑定 task 的稳定项目；返回文档与章节定位、相关度和命中原因，不返回正文，推荐工作流是 `prepare -> search -> read`。
- 第一版文档搜索采用 PostgreSQL `simple` 全文检索、`pg_trgm` 和短词精确子串匹配，不引入向量数据库。路径、显式 title/summary、章节和规范化正文共同参与排序；分块命中在服务层按文档聚合。
- Markdown 原文仍以磁盘文件为唯一真源，但允许把规范化派生分块持久化到 `document_search_chunks`。每次添加、编辑、启动恢复或手动刷新 Workspace 时，以确定性 DocumentCache version 全量替换涉及项目的索引；查询只接受与当前缓存同版本的索引。
- 搜索索引是显式依赖而不是静默优化：控制面数据库、索引状态或当前版本不可用时，`search_context_documents` 返回稳定的 index-not-ready 错误，不扫描进程内 Markdown 兜底，也不返回旧版本结果。
- 项目卡片“查看调用记录”继续作为文档使用历史入口，只展示实际产生 read call 的任务，并保留完整文档树、读取列表和 Markdown 查看；全局链路管理是独立的内部 MCP 可观察性页面，只展示调用树与调用列表，不复用文档浏览功能。
- 通用 `mcp_tool_calls` 和 `mcp_database_calls` 继续保持轻量。只有 `search_database_objects`、`execute_database_query` 把实际请求和最终、有界 MCP 响应写入独立的一对一 payload 表，prepare/read 不建立完整 payload。
- payload 当前对白名单数据库工具自动采集，请求/响应各 1 MB、硬上限 4 MB、保留 7 天。主 Trace API 只返回可用状态，完整内容经 task/call 归属校验的 no-store API 按需读取。到期删除 JSON 但保留状态，采集/清理失败不得改变工具业务结果。
- 当前产品仍是回环地址上的本机单用户服务。数据库 payload 可能包含 SQL 条件值和业务数据，因此详情页明确提示敏感性；如果未来扩大网络边界，必须先增加鉴权、授权、审计访问和更严格的字段脱敏。

### 2026-07-24

- MCP 调用记录采用“`mcp_tasks` 作为任务 Trace 根、`mcp_tool_calls` 作为工具 Span”的统一模型。四个固定工具在 FastMCP 分发入口统一观测，文档读取和数据库调用表继续保存专属明细，通过 `tool_call_id` 关联，避免把不同工具字段堆进通用表。
- 工具调用顺序由 PostgreSQL Identity 生成，API 在同一 task 下按调用 ID 返回稳定 sequence；不让客户端传序号，不使用 `MAX(sequence)+1` 或任务锁。普通顺序不等于因果，只有显式 `parent_tool_call_id` 才形成父子关系。
- 链路观测属于 best-effort 辅助能力：调用开始或完成记录失败时写日志，但不得改变 MCP 工具的业务返回。调用摘要使用工具白名单，不保存 Markdown 正文、完整 SQL、查询结果或连接凭据。
- Context Router Server 只观测发给自身 `/mcp` 的四个内部工具调用。客户端直连其他 MCP Server 的请求不属于本产品链路范围；不实现外部 MCP 连接或代理、客户端调用上报、工具聚合以及跨 Server Trace。
- 历史 read/database 记录在 migration 中映射为 `legacy` 工具调用，保留旧页面数据但不伪造缺失的 prepare 节点、真实开始时间或因果关系。
- task 使用创建时的稳定 `project_id` 作为不可变项目快照，仅 migration 前已失去项目、无法回填 ID 的旧记录兼容 `project_key`。该字段刻意不设置 `document_projects` 外键，确保新任务和已回填任务在项目删除后不丢历史身份、同路径新项目不会继承，也允许默认项目在持久化降级时创建任务。
- 单进程启动时将遗留的内部 `running` 调用收敛为 `error/server_restarted`。Trace API 以 prepare 是否存在、运行中、legacy、重启中断和无法关联的文档/数据库明细计算 `complete / running / partial`；普通无内部调用 task 仍可显示为 partial，系统预览/接入测试任务排除。这是可见性提示，不改变工具结果。

### 2026-07-22

- 本节保留当时的 Project alias 与 task 路由决策作为历史；`20260726_0014` 已把新 task 和 alias 唯一范围提升到 Workspace，旧 `scope='project'` task 才继续使用这里的兼容链路。
- MCP 工具集合固定为 `prepare_task_context`、`read_context_document`、`search_database_objects`、`execute_database_query` 四个；数据源增删不生成动态工具，保证 Codex 和 Antigravity 的工具发现结果稳定。
- 数据库访问统一经过 `task_id -> project_key -> 当前 project -> 项目内 mcp_alias -> live policy`。MCP 参数不接受 project/source/database ID、Host、DSN、口令或客户端自定义查询限制。
- `mcp_alias` 与人类展示 alias 分离，在项目内大小写无关唯一。prepare 只返回可用只读数据库的最小摘要，不连接远端业务数据库。
- 项目数据库选择与 alias 使用单次批量事务更新；事务内先释放旧 alias 再写入最终集合，以支持 A/B 互换并避免前端多请求造成部分状态。
- 第一版数据库 MCP 永久只读：SQLGlot fail-closed AST 与作用域校验、数据库只读事务/ClickHouse readonly settings、只读数据库账号共同构成防护；写 SQL、事务会话和自定义 SQL 工具不在本轮范围。
- Connector 使用静态 Registry 和能力矩阵；Manager lazy 创建、single-flight、发布前 ping、按 source version 与 database update 失效、lease/retiring、每 Source 并发限制和 LRU。应用启动不连接业务数据库，lifespan 退出统一关闭。
- 查询结果按最终 compact JSON UTF-8 字节和行数双重预算，复杂类型递归转为合法 JSON；完整 SQL 和结果不持久化，只记录 SQL SHA-256 与调用元数据。
- ClickHouse V1 使用官方 HTTP/HTTPS Client，支持连接测试、`system.databases` 同步、渐进对象搜索和有界只读查询；未实现 Connector 的 Engine 只允许配置，不在 UI 中伪装成可查询。
- 本项目是本机单用户工具，不增加 OAuth/RBAC；Backend 与 Frontend 端口必须只绑定 `127.0.0.1`。若未来暴露到局域网或公网，必须重新评审鉴权、TLS、CORS 和 task_id 的安全语义。

### 2026-07-19

- 采用“产品 MCP-only、HTTP API 内部保留”的边界，AI 只感知两个 MCP 工具，开发者只使用 Web 查看和管理。
- MCP 不维护全局当前 trace 或当前文档，所有 read 显式绑定 trace，避免多个 AI 任务并发串链。
- AI 可自主跳过 MCP；系统只记录实际 prepare/read，不增加人工反馈、任务成功评分或不读原因字段。
- 项目文档继续放在各自项目仓库，Context Router 只保存可同步索引；cwd 最长 root_path 匹配负责跨项目定位。
- Tasks 页面是可观察性产品，数据源只包含 MCP 任务，Web 文档预览保持 untracked。
- 旧表和 migration 保留历史兼容，运行时路由和页面可以删除。

### 2026-06-27

- 文档体系采用按需读取结构：`AGENTS.md` 只保留一级索引，`docs/DEVELOPMENT_OUTLINE.md` 负责开发大纲，细节放入 `docs/development-details/`。
- 上下文检索不再使用文档切分表或向量相关能力，统一基于完整文档正文和元数据做确定性关键词检索。
- 任务入口路由信息作为 trace 的一等元数据保存，包括 area、入口索引路径、入口规则、route hint、调用来源和 agent 名称。
- 显式传入 area 时，检索优先限定在相同 area 和通用文档内，避免 AI 为一个明确任务读取过多无关 area 的上下文。
