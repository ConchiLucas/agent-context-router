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
| 表关联查询与展示 | [表关联设计](./development-details/table_relation_design.md)、[按表名补全表关联](./development-details/table_relation_complete.md)、[表关联种子怎么写](./development-details/table_relation_seed.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/table_relation_query.py`、`services/table_relation_rules.py`、`api/table_relations.py`、`scripts/seed_table_relations.py`、`table-relation-explorer.tsx`、`lib/table-relations.ts` |
| 接口转发 | [前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/interface_forwarding.py`、`api/interface_forwarding.py`、`interface-forwarding-manager.tsx` |
| 业务值映射、数据库取值规则与接口参数绑定 | [业务功能说明](./BUSINESS_FEATURES.md)、[数据库信息](./DATABASE_INFO.md)、[前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `services/value_mapping.py`、`api/value_mappings.py`、`value-mapping-manager.tsx` |

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
- 浏览器管理面以只读查看为主，并允许既有安全操作和已有系统文档 JSON 正文保存。结构化业务值映射的增删改与候选预览只供本机 AI/运维调用，不在页面提供入口；系统文档的新建、删除和元数据调整同样只供本机 AI/运维，页面只有“保存内容”。
- 工作空间、项目、数据源、数据库清单、项目授权、环境映射/JSON、默认环境和运行配置仍由本机 AI/运维使用既有受校验 API 维护；此类调用不携带 `Origin` 或 `Sec-Fetch-*` 浏览器请求头。不要为了绕过页面限制直接写 PostgreSQL，否则会跳过路径、事务、环境 revision、缓存与 Connector 失效处理。
- 物理数据源配置全局共享，数据库授权继续由 `project_databases` 绑定具体 Project；Workspace task 汇总使用所有子项目当前有效的授权，`mcp_alias` 在整个 Workspace 内大小写无关唯一。
- 每个 Workspace 独立拥有动态环境列表；`local` 固定存在且为默认，`test`、`uat` 或其他名称只按项目实际需要登记。`prepare_task_context` 显式环境记录 `task_explicit`，省略时固定 `local` 并记录 `workspace_default`。环境 task 保存共享 revision，关联变化后旧 task 必须重新 prepare，禁止静默换库。表关联是例外：每个 Workspace 只读取一个已发布基准快照，不继承 task 环境；攀枝花当前基准是 `uat`，其他现有 Workspace 没有快照时按 `local` 规划。
- 数据库实体和项目授权不携带 `test/uat` 语义；环境只是把稳定逻辑别名关联到既有 `project_databases`。一个环境的同一逻辑别名只有一个目标，但多个环境可以复用同一条数据库授权。
- Workspace 可按任意已登记环境保存有界 JSON 对象，用于组件环境差异；JSON 不预设字段，也不要求数据库关联存在。所选环境 JSON 只在显式调用 `read_task_context` 时返回给可信本机 MCP 调用方，严禁进入日志、开发文档、链路摘要或示例输出。
- Workspace 可按环境保存 Nacos 配置档和组件抽取规则，一个环境最多一个配置档。`read_middleware_context` 显式环境优先，省略时继承 task 环境；规则以 JSON 定义 dataId、group 和字段路径。本机工具默认返回明文，显式 `reveal_secrets=false` 时脱敏，响应值永不写入 Trace 摘要或 payload 表。
- 完整 Workspace prepare 的 `access` 包含 `middleware`。工具说明明确允许在本机授权任务的当前回答和连接诊断中返回、使用明文凭据，同时禁止将实际值写入源码、Markdown、持久化日志、无关工具参数或提交记录；`read_task_context` 的通用环境 JSON 不作为 Nacos 中间件实时信息的权威来源。
- 刷新以 Workspace 为单位全量重建可选根入口和全部子项目并统一替换；会遍历并记录全部失败项目，任一入口文档构建失败时仍保留上一版工作空间映射。
- 前端只从 Workspace 树接口获取显式根树或合成根树，从 Workspace 文档详情接口按需获取内存正文；未出现在真实根显式树中的 Project 文档仍保留在 Workspace 搜索和按 ID 读取范围。
- Workspace 根通过 Docker 可写挂载，仅供显式“从数据库恢复”全量覆盖；普通文档读取和扫描不写目标目录。
- MCP `tools/list` 固定为 17 个当前工具，其中业务值映射提供 `search_value_mappings` 与 `resolve_value_candidates`；工具列表不按项目、数据源、中间件或映射记录动态变化。
- 接口转发准备在调用方未指定地址和身份时，先复用当前环境最近成功且仍有效的配置，再选择唯一候选，无法可靠判断才返回待选择；`selection_evidence` 只记录选择来源，不包含请求头。参数默认复用最近成功请求；只有 `refresh_selected`、`refresh_mapped`、`ignore_history` 才调用业务值映射改变历史字段。定向刷新以稳定 `value_key` 标识字段，caller 显式值优先，无法找到不同候选时不生成执行计划。
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
- Context Router 十二个当前 MCP 工具在统一分发入口记录到 `mcp_tool_calls`；任务内顺序由 PostgreSQL 调用 ID 生成，文档/数据库专属明细通过 `tool_call_id` 关联，观测失败不得改变工具业务结果；中间件工具只记录组件数量、脱敏模式和警告数量，不记录连接值；已下线的兼容工具历史仍可查询。
- 调用链路页面记录 Codex、Antigravity 等客户端实际发送到 Context Router `/mcp` 的十二个当前工具调用，并保留三个已下线工具的历史记录；不连接、代理、聚合或接收其他 MCP Server 的调用上报，也不建设跨 Server Trace。
- 顶层页面只读展示 Workspace；进入详情后使用“前端项目 / 后端项目”两页签。环境详情、查看调用记录、查看文档树和查看 MCP JSON 位于 Workspace 工具栏；数据源汇总移动到环境详情页，并由页头环境下拉框统一切换 Nacos、流转说明和授权集合。
- 完整出入参只对白名单数据库工具 `search_database_objects`、`execute_database_query` 自动采集，并通过 no-store 详情 API 懒加载；prepare/search/read 不建立完整 payload 快照。
- 新 task 使用 `scope='workspace'` 和无外键的稳定 Workspace/活动项目快照；`scope='project'` 的旧 task 继续按原 project_id/project_key 读取、搜索和解析数据库，避免升级后历史串链。后端启动会收敛遗留 running 调用，Trace API 与页面明确区分完整、运行中和可能不完整。
- 表关联当前只实现查询展示。关联数据的生成尚未实现（没有命名候选规则、没有跨库推断、没有数据实测），页面数据由种子脚本写入示例。边按「规范化无向对加方向字段」存储，`orientation` 是候选生成期就确定的结构信息而不是实测结论；`cardinality` 统一按父到子存储，`many_to_one` 由读取侧按当前选中表翻转得到，`many_to_many` 由中间表折叠在读取时合成。翻转后的基数直接充当分组依据，页面固定四组 `1 — 1`、`1 — N`、`N — 1`、`N — N`，空组不渲染。junction 折叠是页面级视图偏好，开关在左栏；`tables` 接口按基数额外给出 `folded_*_count`，前端做减法，左栏计数、排序、隐藏判断和顶部总数都跟随折叠状态，和详情实际渲染的行数一致。八个计数由 `project_table_counters()` 走详情同一对视图构造器算出，种子脚本直接复用。`cardinality = 'unknown'` 的边在查询服务就被过滤（不放前端，因为左栏计数存在库里，两处过滤必然对不上）。页面只回答「方向是什么」：状态判定、证据来源、实测指标和表的估算行数、主键、逻辑删除标识既不落库也不展示，一行只有基数徽章和列名对两层，设计保留在 `table_relation_design.md` 等探测流水线实现时再加回。公共字段名单、可展示基数和基数翻转集中在 `services/table_relation_rules.py`，读取路径和种子脚本共用。表关联只有六个只读 GET 接口，没有 rebuild POST，因此不涉及浏览器 POST 白名单和系统任务过滤。
- migration head 为 `20260823_0056`；`0056` 增加 Workspace 业务值映射、关键词别名和接口参数绑定，取值规则只保存稳定数据库别名与结构化表字段，不保存任意 SQL。旧项目 ID、数据库授权和调用历史保持不变。
- 本地服务默认只绑定回环地址；真实 ClickHouse 测试使用根 Compose 的 `integration` profile 和固定镜像版本。
