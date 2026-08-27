# 代码变更记录

- `2026-08-27`：继续回退第 1、3、5、6 组接口识别重构：移除渐进式 MCP 工具发现/代理调用、接口发现意图与共享详情、服务端意图评分和响应规则校验、搜索—选择—执行质量事件，以及 Cursor/Grok 专用接入与页面展示。保留第 2 组接口业务语义、CRUD 与源码证据表影响，也保留写接口执行、Host Runner 扩展方法和成功请求去重。新增 migration `20260827_0072` 将旧能力、评分、校验和事件数据归档为 `archived_*`，历史数据可恢复。
- `2026-08-27`：剥离 Workspace 接口术语及动态限定标签，移除管理弹窗、关联明细、限定词匹配/质量字段和基于术语的地址身份推断；保留接口业务语义、CRUD/表影响、搜索排序证据、搜索—选择—执行闭环与响应验证。新增 migration `20260827_0071` 将旧表和列归档为 `archived_*`，运行时不再读取，历史数据仍可恢复。
- `2026-08-27`：完成接口意图发现与执行准确性改造。新增 `interface_discovery` 任务意图、基于业务实体/CRUD/结果形态/正反例/表影响的确定性候选排序、`read_forwarding_interface_detail` 共享详情 MCP、执行前意图匹配校验和执行后响应结构/业务状态校验。接口可视化同步展示意图证据和验证结果；新增 migration `20260827_0068`，MCP 工具总数调整为 27。
- `2026-08-26`：移除接口转发 MCP 的只读操作类型限制。`prepare_forwarding_request`、`execute_forwarding_request` 和 Host Runner 现在允许已导入接口的 read、write、destructive、unknown 四类操作；Host Runner 同步支持 POST、PUT、PATCH、DELETE JSON 请求。仍保留任务 Workspace/环境、登记路由、服务端身份头、短期计划、请求摘要、配置指纹、防重放、禁止任意 URL/方法/请求头覆盖及有界响应。
- `2026-08-26`：收敛无记忆 AI 的接口执行尾链路。同一计划重试、同一 task 内同接口/环境/身份/请求摘要与配置指纹一致的成功请求由服务端复用既有日志，不重复发送 HTTP 或生成接口可视化记录；接口任务保存 `resolved` 结论时可自动绑定最近一次成功执行证据，避免客户端为了 `tool_call_id` 重新准备和执行。Antigravity 接入模板改为携带 `X-Agent-Name: antigravity` 的 `agy mcp add` 命令，并同步加强 MCP 执行说明。
- `2026-08-25`：完成 task 环境与数据库上下文的不兼容 MCP 改造。环境支持别名，prepare 从任务描述确定并返回固化环境，冲突或多环境直接拒绝；中间件、值映射和接口准备移除环境覆盖。新增 `resolve_database_target`，数据库搜索/查询只接收短期 `database_context_id`；新增 `execute_mapped_data_query` 原子完成已发布映射查询和数据可视化落库。新增 migration `20260825_0064`，并由 `20260825_0065` 强制任务环境三元组完整；客户端需重新连接刷新 tools/list。

本文件用于记录跨模块、数据结构、接口 contract、工程约定等重要代码变更。

## 记录规则

- 按日期追加记录。
- 只记录代码层面的开发信息，不记录普通聊天。
- 简要结论可同步到 `../DEVELOPMENT_OUTLINE.md`。
- 如果内容影响启动、数据库、业务功能或链路流转，需要同步更新对应文档。

## 记录

### 2026-08-25

- 收敛 AI 数据查询收尾参数：统一把持久化 `tool_call_id` 加入成功 MCP 结构化响应；`resolve_value_candidates` 返回可直接调用 `save_data_visualization_query` 的 `next_action.arguments`，包含映射、候选关键词和执行证据调用号；`save_task_visualization_result` 不再暴露手写 `verification`，`resolved` 只通过 `verification_call_ids` 生成可信验证项。
- 修复映射短链路的空 Schema：已发布映射未配置 `schema_name` 时，按 task 环境解析数据库命名空间或唯一允许 Schema，无法唯一确定则返回 `mapping_schema_unresolved`，不再把空值转换成字符串 `None`。`execute_database_query` 缺少 `database/sql` 时返回结构化缺失字段提示。MCP 接入模板新增 Gemini CLI，并为 Codex、Gemini、Antigravity 注入固定 `X-Agent-Name`，prepare 自动记录真实客户端名称用于筛选。
- 优化 AI 数据查询收尾链路：映射解析响应给出权威来源和短链路提示，`save_data_visualization_query` 支持直接引用 `mapping_id` 以及当前 task 成功的解析/查询调用号，跳过重复 Schema 与表关系搜索并可直接写入已查询状态；`save_task_visualization_result` 支持用成功 MCP 调用号生成真实验证项。常见参数错误在 Trace 中记录缺失字段、非法字段和允许值；最终已解决的任务即使中途有可恢复错误，MCP 健康状态也改为“需关注”而不是失败。
- 收紧数据查询映射短链路：data_query 执行契约和 MCP 工具说明要求映射搜索/解析在 prepare 后直接执行，映射未命中才读取数据库列表和探索 Schema；随机请求必须通过 `resolve_value_candidates(selection=random, limit=...)` 完成，不再手写 `ORDER BY RAND()`。调用摘要新增 selection 与有界候选池规模，便于核对 Gemini 等客户端是否采用短链路。
- 业务值映射扩展为数据查询的优先取值入口：`search_value_mappings` 在未指定接口时省略绑定详情，`resolve_value_candidates` 支持从最多 10 条候选中有界随机选择；data_query 执行契约和 MCP 使用说明要求先复用已发布映射，未命中再探索表关系与 Schema。工具总数、数据库结构和前端页面保持不变。
- 增加 AI 任务意图执行契约：`prepare_task_context` 支持声明执行接口、查询数据、普通任务、查询 Bug 和修改 Bug，并持久化错误信号与摘要；prepare 返回写策略、必需步骤和可视化目标。任务收尾按意图校验数据、接口、日志检查及 Workspace 更新证据，只查询 Bug 的 Runtime 写操作由服务端拒绝；任务可视化展示意图。新增 migration `20260825_0063`，旧客户端省略意图时兼容为普通任务并返回提示。

### 2026-08-24

- 实现“AI可视化 → 任务可视化”第一版：复用既有 `task_id` 聚合最近 30 天 MCP、数据、接口和日志记录，新增只读任务列表、详情、稳定游标时间线及跨可视化跳转；新增 `save_task_visualization_result` MCP 工具按 task 脱敏覆盖结构化结论并记录 revision。新增 migration `20260824_0062`，浏览器不创建任务、不编辑结论且不自动轮询。

- 加固三类 AI 可视化：新增 `save_data_visualization_query` MCP 工具，以 task 自动补齐 Workspace/环境/来源并幂等保存数据查询条件；关联查询回写执行状态、耗时与结果规模。数据、接口和日志支持 task 跨模块联动、最近 30 天窗口及统一敏感信息脱敏；接口和日志列表改为稳定游标分页，复制内容保持脱敏。日志只在显式关键词命中时记录，并按稳定因果签名合并事件。新增 migration `20260824_0061`；保留用户手动刷新，不加入自动轮询或新记录提醒。
- 实现“AI可视化 → 日志可视化”第一版：新增 `list_task_containers` 与 `inspect_container_errors` MCP 工具，只允许读取 task Workspace 运行标签注册的 Docker 容器；日志使用非跟随时间/行数/字节上限，提取多行错误并脱敏，未发现错误不落库。同一 task 相同错误幂等更新；新增最新优先的只读列表/详情 API、双栏页面和 migration `20260824_0060`。
- MCP 接口执行改为在线程中等待 Host Runner，并限制最多 4 个并发执行；客户端取消时继续完成回调和日志收尾，Host Job 轮询间隔调整为 0.25 秒，避免同步等待阻塞控制面心跳与完成回调造成假性 `HostRunnerTimeout`。
- 实现“AI可视化 → 接口可视化”第一版：直接聚合真实接口转发日志、任务原始描述与请求计划参数证据，按最新请求倒序展示 Workspace/状态筛选、请求列表和详情，不增加审批状态或重复请求记录表。新增只读列表/详情 API 和 migration `20260824_0059` 日志索引。
- MCP 新增 `read_forwarding_request_history`，允许 Codex、Antigravity 在当前 task Workspace/环境内读取单接口最近请求；响应默认省略、显式读取时限长，账号请求头永不返回。工具可结合现有接口搜索、业务值映射、只读数据库、请求准备和执行链自主组装参数并直接调用接口。
- 实现“AI可视化 → 数据可视化”页面，默认载入本机 AI/运维最新保存的查询条件，支持加载最新、右侧历史记录回填、条件复核和现有关联数据只读查询；没有修改“数据管理 → 关联数据”组件。
- 新增 `POST /api/ai-visualization/query-records` 外部写入接口，以及浏览器可读的最新和历史接口。写入校验工作空间、动态环境与已发布关联表；新增 migration `20260824_0058` 和 `ai_data_query_records`，不保存查询结果。
- 配置管理左侧补齐数据库配置、AI 配置、本地 CLI 配置、MinIO 配置、图片模型配置、Runtime Contract 六个菜单，并对齐共享配置中心的语义图标、柔和背景和贴左选中竖线。六类配置均由本应用通过配置中心 API 自行绘制只读详情；只有 AI 默认项写入本地，数据库密码、AI/API Key、MinIO 凭据及 Runtime Contract 密钥默认遮罩。
- 新增“配置管理 → AI 配置”页面及 `/api/shared-config/ai` 读取、刷新、默认项保存接口。Provider、模型、地址和明文密钥仅从 `ai_share_config` 配置中心实时读取；页面默认脱敏展示密钥，按眼睛按钮才临时显示明文。本机只持久化默认 Provider ID，首次有效读取自动初始化；本机默认已被配置中心删除时自动回退中心 `activeProviderId` 并提示。新增 migration `20260824_0057` 和 `shared_ai_defaults` 单例表。

### 2026-08-23

- 接口转发 MCP 在调用方未传地址和身份时，自动复用当前环境内最近一次成功且仍有效的配置；无历史时自动选择唯一候选，多个候选无法判定才返回 `needs_selection`。显式账号/角色先缩小地址范围，响应和 MCP 摘要新增不含敏感值的 `selection_evidence` 来源。
- 映射管理的关键词输入框与搜索按钮在所有断点保持同一行，搜索按钮固定不收缩且文字不换行。
- 映射管理页面改为纯只读展示，移除新增、编辑、保存、删除及接口参数解绑操作；写入与预览能力继续保留在 AI/运维接口。
- 顶部导航收敛为“工作空间、数据管理、接口管理、AI可视化、系统中心”五组；数据管理位于接口管理之前，其余页面按业务域进入四个统一交互的下拉菜单，并补齐方向键、Esc、点击外部关闭和焦点恢复。
- 新增顶部“映射管理”页面：按 Workspace 展示和维护业务值名称、稳定 `value_key`、关键词别名、结构化数据库取值规则及现有接口参数绑定。页面省略状态、可选 Schema、手动接口搜索/绑定和候选值预览；新建记录直接发布，完整维护与预览能力继续由本机 AI/运维接口提供。
- 新增 `ValueMappingService` 与 `/api/value-mappings` 管理/预览接口。取值规则只保存只读数据库 `mcp_alias`、表、字段和标量等值过滤，预览由服务端生成 SQL、执行标识符校验并复用现有数据库环境解析、Connector 和 `SqlSafetyPolicy`，不开放任意 SQL。
- 新增 migration `20260823_0056` 和 `interface_value_mappings`、`interface_value_mapping_aliases`、`interface_value_mapping_bindings`；关键词在 Workspace 内唯一，一个接口参数只能绑定一个业务值。新增 `search_value_mappings` 与 `resolve_value_candidates` MCP：前者按业务词或接口参数查找已发布映射，后者继承任务环境并执行结构化有界只读规则，最多返回 10 条候选且不接受任意 SQL。
- `prepare_forwarding_request` 用 `value_strategy` 替代布尔历史开关：默认 `reuse_successful`；`refresh_selected` 只刷新 `refresh_value_keys`，`refresh_mapped` 刷新接口全部映射值，`ignore_history` 放弃历史重建。调用方字段跳过映射查询；刷新候选优先排除历史旧值，失败返回 `needs_value_resolution` 且不生成执行计划。MCP 调用摘要只记录策略和刷新 key 数量。

### 2026-08-22

- 接口转发 prepare 增加参数证据引擎：只复用同接口、同环境、同地址、同身份的最近成功日志，移除验证码、临时令牌、时间戳等易失历史值，历史页码重置为 1、分页大小上限为 20；调用方值保持最高优先级。MCP 返回逐字段来源、证据和可信度，并明确提示未绑定数据库字段的历史 ID 尚未验证；计划持久化证据用于后续审计。新增 migration `20260822_0055`。
- 接口转发 MCP 增加 Host Runner 执行通道：控制面完成计划、指纹和只读校验后创建单次短租约任务，具备 `interface-forwarding` 能力的 Runner 在宿主机 VPN 网络执行服务端组装的 GET/POST 请求，再把有界结果写入原请求日志；请求头不落任务表、不返回 AI，禁止任意 URL、重定向和超限正文。新增 migration `20260822_0053`。
- UAT 实测确认 MTP 承运商分页接口经 Host Runner 返回 HTTP 200；同时确认 c12-data 原始 Controller 路径即使映射到 MTP 地址仍返回 404，因此取消通用前缀推断并禁用原始 c12-data 接口执行，后续只开放明确登记的 MTP 包装接口。新增 migration `20260822_0054`。
- 接口转发“全部接口”和单服务列表统一按最近请求时间倒序展示，未请求接口稳定排在末尾；接口详情把“请求日志”调整为第一个 Tab，并在每次打开详情时默认优先加载和展示日志。
- 新增 `refresh_interface_request_contracts` 源码契约刷新脚本：扫描 c12-mtp、c12-portal、c12-data、c12-sys 的 Spring Controller，按 Controller、方法和路径匹配已导入接口，补齐 `@PathVariable`、`@RequestParam` 与保留的 Swagger 请求体契约；本次刷新 450 个 Controller 文件、2312 个接口，其中 2144 个精确命中源码。修正只读分类优先级，将 GET 取消订阅明确归为写操作。新增 migration `20260822_0052`，依据 c12-data 的 `DATA_CONTEXT_MTP_PATH` 将网关前缀修正为 `/data`，最终经 c12-mtp 地址调用 `/data/data-api/...`。
- 新增接口转发 MCP 三段式调用：按任务工作空间搜索接口、结合环境/地址/账号角色/历史参数生成 10 分钟只读执行计划，再以计划 ID 与请求摘要单次执行。请求头仅在服务端注入，禁止任意 URL/方法/请求头覆盖；响应限制为 1 MiB、关闭自动重定向并记录 task/tool/plan/账号角色、摘要、耗时与截断状态。服务新增 direct/gateway/disabled 路由模式，现有 c12-data 显式经 c12-mtp 网关转发。

- 接口转发 overview 聚合每个接口的最近请求时间，当前服务和全部接口视图都按最近请求倒序并将未请求接口稳定排在后面；前端在接口名称旁显示“已请求”标识及最近请求时间提示，关闭测试弹窗后自动刷新排序。
- 接口转发增加仅供 AI/运维使用的受校验外部结果登记接口，用于 Docker 容器无法继承宿主机 VPN 路由时，将宿主机真实分页测试结果写入原接口日志；写入前校验接口、服务地址和身份归属。
- 接口转发请求日志保存执行时的身份角色快照，日志标题可区分相同账号的货主和承运商测试；新增 migration `20260822_0050`。
- 接口转发身份唯一约束调整为“转发地址 + 登录账号 + 角色”，同一账号的不同角色在详情中分别成卡；新增 migration `20260822_0049`。
- 接口转发配置详情改为按登录账号聚合：当前环境有几个不同账号就展示几个账号区块，每个区块列出该账号关联的全部转发地址、接口服务和请求头；环境地址列表不再充当账号过滤器。
- 接口转发登录账号增加精简角色标识，并在只读转发配置详情中以账号旁徽标展示。新增 migration `20260822_0048`。
- 接口转发配置详情改为纯展示，移除地址和账号的新增、编辑、删除按钮及表单状态；后端写入接口继续保留给 AI/运维使用。
- 接口转发地址增加接口服务映射：同一 Workspace 环境可为 `c12-portal`、`c12-mtp`、`c12-data` 等服务分别维护同名地址；接口测试仅列出当前服务地址，后端 execute 同步拒绝跨服务转发。新增 migration `20260822_0047`。
- 接口转发主列表保留接口名称、Controller 名称、接口路径三列信息和紧凑操作列，请求方式与路径同列；接口名称列缩短约三分之一，固定列宽并在单元格内省略长文本，移除横向滚动。接口路径支持鼠标悬浮和键盘聚焦展示完整路径。请求测试移动到列表操作栏，接口说明、Controller 描述、入出参、日志和删除集中到接口详情弹窗。
- 接口转发列表增加 Controller 名称和 Controller 描述；Swagger/OpenAPI 导入时读取 operation tag 和顶层 tag 描述，缺少描述时生成简短中文职责。新增 migration `20260822_0046`。
- 移除顶部导航右侧的只读说明；新增“AI可视化”一级下拉菜单及接口可视化、数据可视化、日志可视化三个预留子菜单，当前不渲染业务内容。
- 接口转发配置扩展为“Workspace 环境 → 多个具名转发地址 → 每个地址多个账号”；地址名称用于区分门户端、运营端等入口，允许不同名称复用相同 URL。新增 migration `20260822_0045`。
- 合并接口转发的“环境管理”和“身份管理”为“转发配置”详情：环境严格读取当前 Workspace 环境注册表且不支持在此增删；每个环境仅维护基础地址，身份仅维护登录账号和请求头。新增 migration `20260822_0044` 对齐数据约束和接口参数。
- 从 vibecoding-utils 迁移“接口转发”完整功能到顶部菜单：按 Workspace 管理服务树和接口，支持 Swagger 2/OpenAPI 3 JSON 导入、接口搜索、转发环境、请求身份、请求测试、入参/出参结构和日志。
- 新增 migration `20260822_0043` 及六组接口转发表；每个接口记忆最后一次环境、身份、请求参数和响应。浏览器写入边界只对 `/api/interface-forwarding` 专用管理/执行路径开放。

### 2026-08-21

- 应用一级导航从固定左侧栏移动到粘性顶部栏，保留原菜单顺序、图标、文字、选中状态和页面切换行为；窄屏使用品牌行加可横向滚动的带文字菜单行，全屏型页面高度同步扣除顶部栏。
- 六个一级菜单页面统一使用“文档统计”的内容外边距：桌面左右各 24px、平板和窄屏各 16px；间距由共享应用内容外壳提供，页面根节点不再重复叠加横向 padding。
- 表关联页在 Workspace 表清单加载完成后默认选中第一张可见表并读取详情；已有用户选择时保持不变，切换 Workspace 后按新清单重新选择。

### 2026-08-20

- 表关联 MCP 改为 AI 两阶段读取：`search_relation_tables` 只返回轻量候选表和截断标记；`read_table_relations` 默认只返回结构化 child/parent 关系，写入/更新入口由 sections 按需请求，证据改为 `none/uncertain/all` 三档。删除重复 task/count/class 字段，未解析关系改为显式 warning。
- 新增 migration `20260820_0040` 和 `workspace_environments`：每个 Workspace 独立维护动态环境，`local` 固定存在、不可删除且为默认；移除逐 MCP 默认环境表和 `tool_default` 运行语义。
- Nacos 配置、通用环境 JSON、数据库目标和 task 快照引用 Workspace 环境键。一个环境最多一个 Nacos 配置；数据库实体不携带环境语义，多个环境允许复用同一条项目数据库授权。表关联独立为 Workspace 唯一发布快照，版本环境仅记录基准来源。
- 关联数据关键词使用浏览器本地历史，按 Workspace、运行环境、库和表隔离；每个 Workspace 环境另外记录最后一次成功查询的库、表和关键词，重新进入页面时自动恢复。历史下拉最多保留 12 条，手动输入始终可用。
- 关联数据查询结果首卡固定为搜索框所选表，其后才展示直接关联表。
- 关联数据关键词改为关联字段完整值精确匹配；多条命中随机选一条起点记录并高亮命中列和值，后续卡片及分页固定使用该条记录的关联键，同时高亮各关联表的目标关联列与匹配值，零记录关联卡片不再展示。
- `prepare_task_context` 省略环境时固定 `local`；`read_middleware_context`、`read_table_relations`、`search_relation_tables` 省略时继承 task 环境，显式环境始终优先。数据库上下文、对象搜索和只读查询始终使用 task 快照。
- Workspace 环境详情页改为一个页头下拉框驱动全部内容；数据源汇总从工作空间项目页签移动到环境详情，并按所选环境过滤。页面已覆盖桌面、平板和窄屏布局。

### 2026-08-11

- `prepare_task_context` 的文档导航改为确定性的任务局部三层投影：真实 Workspace 根 `AGENTS.md` 存在时固定作为第一层；缺少真实根时，才从活动 Project 入口或合成根开始。投影裁剪不改变 Workspace 范围的 `search_context_documents` 和 `read_context_document`。
- 新增 migration `20260811_0028`、`workspace_nacos_profiles` 和固定 MCP 工具 `read_middleware_context`。配置档按 Workspace 与 `default/test/uat` 保存 Nacos 连接和声明式组件抽取规则；工具根据 prepare 是否显式选择环境读取，本机默认明文且可显式关闭 reveal 获取脱敏视图，Trace 仅保存数量与开关且不建立 payload 快照。
- `read_middleware_context` 的环境选择改为显式优先：prepare 未传环境时固定读取 `default/local`，显式传 `test/uat` 时读取同名配置档。数据库继续保留省略环境时使用 Workspace 当前环境的既有语义。
- prepare 的完整 Workspace 能力增加 `middleware`；MCP Server 与工具描述改为“授权任务允许读取并临时使用、禁止展示或持久化”，并明确 `read_task_context` 的通用环境 JSON 不是 Nacos 中间件实时信息的权威来源。
- 本机 `read_middleware_context` 的 `reveal_secrets` 默认值改为 `true`，未传参时返回明文，显式传 `false` 时脱敏；Trace 只记录 reveal 状态和数量，仍不保存响应值。

### 2026-07-30

- 新增 migration `20260730_0022`，删除 `workspaces`、`data_sources`、`project_databases` 和 `workspace_database_environment_configs` 的 `enabled` 列，并重建不含启停字段的查询索引。后端实体、仓库、Schema、API 与前端类型同步移除启停逻辑和状态展示。
- 环境配置不再用布尔字段区分 JSON-only 与数据库映射模式：存在数据库映射记录时按 TEST/UAT 目标解析；仅存在环境 JSON 时继续使用原有 Workspace alias，兼容单环境项目。
- 工作空间、项目、数据源、项目授权、环境映射/JSON和运行配置前端统一改为只读；移除 CRUD、启停、同步、刷新、保存、物化和执行交互，保留查看、筛选、复制、密码按需 reveal、连接测试、MCP 接入测试、文档/调用历史及 Runtime Runner 记录查看。
- 新增前端 `browser-api-policy.ts`，`lib/api.ts` 和 `runtime-api.ts` 在请求发出前拒绝浏览器配置写操作。安全 `POST` 白名单仅包含数据源连接测试、密码 reveal、MCP integration test 与 Workspace prepare preview。
- 新增后端 `BrowserReadOnlyMiddleware`，对携带任意 `Origin` 或浏览器 Fetch Metadata 的请求执行同一方法白名单，并对配置写请求返回 `405 management_read_only`；不携带这些浏览器请求头的本机 AI/运维调用方继续使用既有受校验管理 API。
- 运行配置前端改为加载快速/完整部署文件和已有运行记录、详情、日志；后端写 API 与 Runtime Runner MCP 保留，供 AI/运维执行正确的物化、更新和副作用处理。
- 移除启动阶段由默认项目环境变量自动声明根项目的兼容逻辑及对应 Settings 字段；Compose 不再声明或自动创建 Workspace/Project。本次无数据库 migration。

### 2026-07-27

- 新增 migration `20260727_0016` 和 `document_projects.document_relative_path`，从旧 `agents_path` 相对 Workspace 根目录的位置回填，并增加 Workspace 内文档入口唯一约束。`agents_path` 保留为绝对路径兼容镜像。
- Workspace Project API、前端类型和 MCP `PreparedProject` 同时返回源码 `relative_path` 与文档入口 `document_relative_path`；新 Workspace 项目入口限制在 `docs/` 下并以 `AGENTS.md` 结尾。
- ProjectRegistry 分离 `resolved_project_root` 与 `resolved_agents_path`。项目缓存从 docs 入口递归构建，cwd 和 `active_project` 继续按源码目录定位，避免集中式文档目录改变任务归属。
- Workspace 刷新改为遍历全部项目并聚合入口错误；任一失败仍不替换旧缓存。前端刷新失败后重新拉取项目卡片和工作空间摘要，使全部错误立即可见。
- 工作空间详情的新增/编辑表单、项目卡片和删除说明同步采用源码/文档双路径，并提供 `docs/{kind}/{项目目录名}/AGENTS.md` 建议。

### 2026-07-26

- 新增 migration `20260726_0015` 和 Workspace 文档独立搜索状态/分块表。工作空间固定自动探测根 `AGENTS.md`：存在时作为真实聚合树根并参与 prepare/search/read，不存在时保持合成根；不新增 Workspace 路径配置字段，也不把根文档伪装成 frontend/backend Project。
- Workspace 刷新同时临时构建根入口和全部 Project，成功后统一替换；根入口与 Project 重复映射时 Workspace 所有权优先，Project 之间继续按最深项目去重。旧 `scope='project'` task 仍只访问原 Project 文档。
- 新增 migration `20260726_0013` 和 `workspaces` 表；`document_projects` 增加非空 `workspace_id`、`relative_path`、工作空间外键、工作空间内相对路径唯一约束和查询索引。旧项目按同 ID Workspace + 根项目 `.` 回填，保留项目 ID、数据库授权和全部调用历史。
- 新增 migration `20260726_0014`。`document_projects` 增加 `frontend/backend` 的 `project_kind` 并删除 Project enabled；`project_databases` 增加 `workspace_id`，`mcp_alias` 唯一索引从 Project 提升到 Workspace；`mcp_tasks` 增加 `scope`、Workspace 快照和可选活动项目快照。
- 0014 升级前的 task 保持 `scope='project'`，并按原项目回填 Workspace/活动项目字段；新 prepare 写入 `scope='workspace'`。read/search/database 根据 scope 选择 Workspace 新链路或 Project 兼容链路，旧历史不会扩大权限，也不会被同路径新项目接管。
- `prepare_task_context` 工具名和参数保持不变，cwd 改为最长前缀匹配 Workspace；最深 Project 仅作为 `active_project`。返回值包含 Workspace、全部 Project 的类型/相对路径、聚合文档树，以及全部子项目当前有效且在 Workspace 内 alias 唯一的数据库摘要。
- ProjectRegistry 新增 Workspace 聚合缓存：根 `AGENTS.md` 存在时使用真实入口，不存在时使用合成入口。文档树、文档详情、MCP JSON、调用记录和刷新均新增或切换到 `/api/workspaces/{id}` 路径；Workspace 刷新先构建根入口和全部子项目，任一文档构建失败时保留上一版完整映射。Project 只保留新增、编辑和删除，不再有启停、逐项目刷新或逐项目上下文 API。
- 文档搜索对 Workspace task 查询根文档独立索引和各 Project 当前版本索引，再按 Workspace 优先、最深 Project 所有权去重；read 从 Workspace 聚合缓存读取；数据库访问按 `task_id -> workspace snapshot -> Workspace mcp_alias -> 所属项目关联` 解析。授权记录仍属于 Project，Workspace 数据源汇总不复制授权或策略。
- 前端一级导航由项目管理改为工作空间管理；详情页改为“前端项目 / 后端项目 / 数据源汇总”三页签。刷新映射、调用记录、文档树、MCP JSON 和 MCP 接入移到 Workspace 工具栏，项目卡片只保留“编辑项目 / 管理数据源 / 删除项目”。
- MCP 接入测试请求由 `project_id` 改为 `workspace_id`，真实执行 Workspace 匹配、prepare、search 和 read；接入信息的可匹配数量改为 Workspace 数量。

以下更早日期保留当时已落地行为作为历史；其中 Project task、Project enabled、项目内 alias 和项目卡片上下文入口均已被本日 0014 与 Workspace UI 改造取代。

### 2026-07-25

- 新增第五个固定 MCP 工具 `search_context_documents(task_id, query, limit)`：在 task 绑定项目内按路径、标题、概要、章节和正文检索，返回文档 ID、匹配章节、相关度和命中原因，完整正文继续由 `read_context_document` 按需读取。
- 新增 migration `20260725_0012`、`pg_trgm`、`document_search_index_states` 和 `document_search_chunks`；Markdown 经 Front Matter 剥离、章节解析、NFKC 规范化和有界分块后建立 PostgreSQL `simple` FTS 与 trigram 索引，原始 Markdown 仍以磁盘为真源。
- 项目新增、编辑、启用、启动恢复和刷新成功时按确定性文档版本全量替换搜索索引。搜索严格校验 task 项目和当前 index_version，索引缺失、失败或过期时明确报错，不回退内存扫描。
- MCP 接入面板、工具发现和全局链路筛选同步扩展到五个内部工具；文档搜索调用只记录脱敏参数/结果规模，不保存查询原文、Markdown 正文或完整 payload。
- 项目卡片“查看调用记录”恢复为独立的文档调用历史全屏弹窗，任务列表只返回实际产生文档 read call 的任务；链路管理解除项目入口耦合，只保留调用树和调用列表，不再加载完整文档树或 Markdown。
- 新增 migration `20260725_0011` 与 `mcp_database_tool_payloads`：仅为 `search_database_objects`、`execute_database_query` 保存有界请求和最终 MCP 响应，默认请求/响应各 1 MB、硬上限 4 MB、保留 7 天，并在启动及运行期间 best-effort 清理。
- Trace 主详情增加数据库 payload 可用状态，新增按 task_id/tool_call_id 校验归属的 no-store 详情接口；前端数据库节点增加懒加载全屏详情弹窗，支持请求/响应 Tab、SQL/JSON、复制、截断与历史未采集/过期/采集失败状态。
- 文档工具继续只保存脱敏摘要和读取 artifact，不保存 Markdown 正文或完整出入参；数据库 payload 采集失败不会影响原 MCP 调用。

### 2026-07-24

- 新增 migration `20260724_0009` 和 `mcp_tool_calls` 通用链路表；文档读取、数据库调用增加可空唯一 `tool_call_id`，既有历史按时间恢复为 `legacy` 调用。
- FastMCP 四个固定工具接入统一调用观测，记录 Server、工具名、状态、起止时间、耗时、稳定错误码及脱敏摘要；prepare 成功后关联新 task，后续调用在执行前生成运行中节点，观测失败不影响业务调用。
- 新增统一 MCP Trace 列表和详情 API，服务端返回稳定 sequence 与文档/数据库 artifacts，保留旧任务历史接口兼容。
- 前端增加“链路管理”一级导航，提供任务搜索、Agent、四个内部工具和状态筛选，以及调用树、调用列表、文档树和脱敏调用详情；复用文档树、Markdown 弹窗与批量文档横排交互。
- 明确链路产品边界：只记录进入 Context Router `/mcp` 的四个内部工具调用，不连接、代理或聚合外部 MCP，不接收外部调用上报，也不规划跨 Server Trace。
- 新增 migration `20260724_0010`，为 task 保存稳定、无外键的 project_id 快照并按旧 project_key 回填历史；read 和数据库授权优先按稳定 ID 解析，项目删除或同路径重建不会串链。
- 后端启动时恢复遗留 running 调用为 `error/server_restarted`；Trace API 增加 `complete / running / partial` 及 warning code，缺 prepare 或没有内部调用的普通 task 也作为 partial 可见，前端以“完整 / 运行中 / 可能不完整”呈现链路可见性。
- 后续三个 MCP 工具的 task_id 改为严格整数，拒绝字符串与布尔值；链路 best-effort 写入、完成和恢复统一隔离非预期 Exception，确保观测异常不改变工具业务结果。

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
# 关联数据浏览（2026-08-22）

- 新增顶部“关联数据”菜单和 `relation-record-explorer.tsx`，按工作空间、动态环境、数据库和表选择查询。
- 新增安全只读 `POST /api/workspaces/{id}/relation-records/search`：字段、表和关系来源固定为已发布表关联，关键词只匹配当前表的关联字段；查询直接关联表，非 1:1 每页 3 条。
- 数据表保留全部返回列并在卡片内横向滚动；字段表头支持悬浮和键盘聚焦查看注释；分页采用首页、上一页、当前页、下一页、末页的紧凑布局。
