# Context Router MCP 使用说明

## AI 使用原则

- 新窗口遇到业务规则、启动、数据库或跨层链路任务时，先识别用户主意图，再调用 `prepare_task_context(task, cwd, agent_name, intent_type, error_signal?, intent_summary?, capability_hints?)`。`intent_type` 只能是 `interface_discovery`、`interface_execute`、`data_query`、`task_execute`、`bug_investigate`、`bug_fix` 或 `code_change`；仅查找、比较、说明接口使用 `interface_discovery`，服务端也会纠正被误报为执行的接口发现描述。
- prepare 在真实 Workspace 根 `AGENTS.md` 存在时固定以它为第一层；缺少真实根时，才以 cwd 命中的 Project 入口或合成根为第一层。只返回显式下两级，每个节点只有 `document_id`、`summary` 和 `children`。
- 目标不明确、目标文档未进入三层投影或需要按术语定位时，调用 `search_context_documents(task_id, query, limit)`；它搜索当前 task 绑定 Workspace 的全部映射文档，返回文档与章节定位，不返回完整正文。
- 选择文档后调用 `read_context_document(task_id, requests)`；task_id 必须来自当前 prepare，不跨任务复用。
- requests 可同时包含多个 document_id 和可选 section，返回顺序严格保持输入顺序。
- 导航树不等于全部可搜索文档，更不等于完整正文；不要一次读取所有 Markdown 内容。
- 明确文件、符号或纯源码定位可以直接检索项目目录。
- prepare 返回的文档树没有相关上下文时，继续使用正常源码与本地工具完成任务，不要阻塞。
- prepare 会按 Workspace 环境 key、展示名称和别名识别任务文字中的环境，并返回固化后的环境快照；同一句话出现多个环境或显式断言与文字冲突时必须修正任务描述后重新 prepare。后续工具不能覆盖环境。
- 任务需要数据库摘要或环境 JSON 时调用 `read_task_context(task_id, sections)`；不把返回的 alias 直接传给查询工具。
- 任务需要 Redis、MQ、ES、MinIO、任务调度或对象存储等中间件的实时连接、配置或故障排查信息时，必须优先调用 `read_middleware_context(task_id, components?, reveal_secrets?)`。它只继承 task 环境。本机工具默认返回明文；需要脱敏视图时显式传 `reveal_secrets=false`。
- 原始数据库操作先调用 `resolve_database_target(task_id, mapping_id?, table_name?, business_hint?)`。只有它返回的 `database_context_id` 可以传给数据库工具；上下文绑定 task、环境 revision 和物理库，不能跨任务复用。
- Schema 不明确时调用 `search_database_objects(task_id, database_context_id, object_type, pattern, detail, ...)`。优先使用 `names`，需要元数据时再升到 `summary`，只有确认目标后才用 `full`。
- 查询数据时调用 `execute_database_query(task_id, database_context_id, sql)`；只提交一条必要的只读 SQL。即使 SQL 自带 LIMIT，仍以服务端行数、字节数、超时和安全策略为准，并检查返回的 `truncated`。
- 数据查询或接口参数出现业务名称、ID、编码、编号时，在 prepare 后直接调用 `search_value_mappings`，不需要先读取数据库列表。命中已发布规则后直接调用 `resolve_value_candidates`，不再为确认映射来源调用 `read_task_context`、Schema 搜索或原始 SQL；只有没有合适映射时才进入这些探索链路。未指定 `interface_id` 的搜索不会返回接口绑定明细。需要“随机一个”时使用 `selection=random` 并把 `limit` 设为用户要求的数量，不再执行 `ORDER BY RAND()`。解析结果的显示字段已经满足需求时，直接复制响应中的 `next_action.arguments` 调用 `save_data_visualization_query`；其中已包含 `mapping_id`、选中候选关键词和真实 `execution_tool_call_id`，由服务端补齐库、Schema、表并把记录标为已查询，不再搜索 Schema 或表关系。
- 不尝试写操作、跨库查询、外部表函数、文件/网络读取函数或调用方 SETTINGS。工具拒绝后应调整为更小、更明确的只读查询，而不是绕过策略。

## AI 标准执行流程

1. 先把用户的主意图声明给 `prepare_task_context`，创建一次任务，并在后续文档、数据库、接口、日志和运行操作中始终复用同一个 `task_id`。读取返回的 `execution_contract`；其中 `mutation_policy`、`required_steps` 和 `visualization_targets` 是当前任务的执行契约。
2. 核心文档工具始终直接调用：目标不明确时执行 `search_context_documents`，取得 document_id 后执行 `read_context_document`。它们不会出现在 `discover_task_tools` 中，也不能包装进 `invoke_task_tool`。
3. 数据库、映射、接口、日志、中间件和表关联属于专业动作。优先使用 prepare 返回的 `recommended_actions`；当前子目标没有合适动作时执行 `discover_task_tools`，再把动作返回的 `name` 作为 `tool_name`、原样复制 `definition_revision`，通过 `invoke_task_tool` 调用。禁止使用旧字段 `action_name`。
4. 根据任务意图选择最短的授权链路取证或修改；不要为了填充可视化页面调用无关工具。省略 `intent_type` 只用于兼容旧客户端，服务端会按 `task_execute` 处理并返回 warning。
5. 每个成功的 Trace 调用都会在结构化响应中返回 `tool_call_id`。完成实际验证后，在最终回复用户前调用一次 `save_task_visualization_result`：阶段性且非终态使用 `investigating`；只有目标完成并引用至少一项当前 task 的成功调用时使用 `resolved`；遇到明确阻塞时使用 `failed`，并记录根因和安全的下一步。接口执行成功后可省略 `verification_call_ids`，服务端自动绑定当前 task 最近一次成功的 `execute_forwarding_request`；不要为了寻找调用号重新准备、重新执行接口或读取无关上下文。不要手写验证对象。
6. 结构化结论只保存脱敏摘要、工作空间相对代码位置、建议和验证结果，不保存凭据、原始日志或推测。保存记录不能替代给用户的最终答复。

### 意图路由

| intent_type | 执行要求 | 服务端可视化与约束 |
| --- | --- | --- |
| `interface_execute` | 搜索接口、按历史和映射组装参数、准备并执行请求计划 | 已导入的读取、新增、修改、删除和未分类接口均可执行；接口成功或失败都自动写接口可视化，没有真实执行记录不能标记 `resolved` |
| `interface_discovery` | 搜索、比较或说明接口，不执行请求 | 搜索返回结构化匹配分数和原因；歧义或详情问题才读取 `read_forwarding_interface_detail`，完成后直接保存任务结论 |
| `data_query` | 业务值优先走现有映射；未命中时再定位关系表和 Schema，查询后调用 `save_data_visualization_query` | 初始化数据可视化查询条件；没有条件记录不能标记 `resolved` |
| `task_execute` | 按最短授权链路完成普通任务和验证 | 正常写任务可视化结论 |
| `bug_investigate` | 只查询和取证；有错误信号时检查当前 Workspace 已注册容器 | 禁止 `apply_workspace_changes` 和 `start_workspace`；确认真实错误才写日志可视化 |
| `bug_fix` | 有错误信号时先查注册容器，再修改、更新 Workspace 并验证 | 缺少日志检查或 Workspace 更新证据时不能标记 `resolved` |
| `code_change` | 使用客户端原生源码工具开发或重构，按需叠加文档、数据库、接口、日志等证据 | 允许代码修改；Context Router 不代理任意文件编辑或 Shell |

### 多客户端验收矩阵

Codex、Gemini CLI、Antigravity CLI、Cursor Agent 和 Grok CLI 使用同一套 MCP 合同。客户端配置必须发送稳定的 `X-Agent-Name`，服务端调用链据此区分客户端。

| 场景 | 必验主链路 | 通过条件 |
| --- | --- | --- |
| 文档定位 | `prepare → search_context_documents → read_context_document` | task_id 全程一致，search 不返回正文，read 成功 |
| 普通代码开发 | `prepare(code_change) → 客户端原生源码工具 → 验证 → save_task_visualization_result` | MCP 不限制源码编辑，结论引用真实验证调用 |
| 数据查询 | `prepare(data_query) → 映射优先；必要时 discover/invoke 数据库动作` | 环境由 task 固化，数据库目标来自不透明 context_id |
| 接口执行 | `prepare(interface_execute) → 搜索/历史/准备/执行` | 可执行已导入且路由可用的读取或写入计划，并生成接口可视化记录；同一 task 的同配置同请求成功后再次调用只复用结果，不发送第二次 HTTP |
| Bug 查询 | `prepare(bug_investigate) → 日志/数据/接口只读取证` | 不执行代码或运行写操作，真实错误进入日志可视化 |
| Bug 修复 | `prepare(bug_fix) → 取证 → 修改 → Workspace 更新 → 验证` | 主意图不因辅助取证变化，结论引用真实成功证据 |

主意图不排斥辅助链路：例如 `bug_fix` 可以同时查询数据或执行接口，并由实际工具调用分别生成数据或接口记录。接口转发不再按 `operation_kind` 拦截写操作；Agent 必须让所选接口与用户明确意图一致。MCP 只能阻止 Context Router 的 Workspace 运行写操作，不能拦截编码客户端自己的文件编辑能力，因此 `bug_investigate` 的只读要求还必须遵守返回的 `mutation_policy=forbidden`。

任务可视化详情中的“调用链路”只打开同一 `task_id` 的 Context Router MCP Trace；返回任务详情后仍保持原任务选择。系统中心的调用链路入口继续展示全部任务。

## 下一层文档

| document_id | 适用任务 |
| --- | --- |
| `context-router-prepare-guide` | 需要了解 prepare 参数、Workspace/active project 识别和返回范围 |
| `context-router-search-guide` | 需要按关键词定位文档、章节并理解相关度和索引错误 |
| `context-router-read-guide` | 需要了解批量文档、精确章节、顺序和 read_call_id |
| `context-router-trace-guide` | 需要理解 Tasks 页面记录了什么 |
| `context-router-routing-guide` | 需要按 startup/database/frontend/backend/business/debugging 路由 |

MCP 的 `tools/list` 当前由运行时注册表生成，本版共 27 个工具。接口查找先调用 `search_forwarding_interfaces`，按 `match_score`、`match_reasons`、CRUD 和业务对象判断；歧义或参数、响应、影响表问题再调用 `read_forwarding_interface_detail`。`interface_discovery` 返回 `goal_completed=true` 后只保存结论，不准备或执行请求；`interface_execute` 才继续历史、映射、准备和执行链路。其他工具的终态规则保持不变。
