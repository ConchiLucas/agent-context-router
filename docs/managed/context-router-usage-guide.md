# Context Router MCP 使用说明

## AI 使用原则

- 新窗口遇到业务规则、启动、数据库或跨层链路任务时，先识别用户主意图，再调用 `prepare_task_context(task, cwd, agent_name, intent_type, error_signal?, intent_summary?)`。`intent_type` 只能是 `interface_execute`、`data_query`、`task_execute`、`bug_investigate` 或 `bug_fix`；只有后两类可以声明 `error_signal=true`。
- prepare 在真实 Workspace 根 `AGENTS.md` 存在时固定以它为第一层；缺少真实根时，才以 cwd 命中的 Project 入口或合成根为第一层。只返回显式下两级，每个节点只有 `document_id`、`summary` 和 `children`。
- 目标不明确、目标文档未进入三层投影或需要按术语定位时，调用 `search_context_documents(task_id, query, limit)`；它搜索当前 task 绑定 Workspace 的全部映射文档，返回文档与章节定位，不返回完整正文。
- 选择文档后调用 `read_context_document(task_id, requests)`；task_id 必须来自当前 prepare，不跨任务复用。
- requests 可同时包含多个 document_id 和可选 section，返回顺序严格保持输入顺序。
- 导航树不等于全部可搜索文档，更不等于完整正文；不要一次读取所有 Markdown 内容。
- 明确文件、符号或纯源码定位可以直接检索项目目录。
- prepare 返回的文档树没有相关上下文时，继续使用正常源码与本地工具完成任务，不要阻塞。
- 任务需要数据库别名或环境 JSON 时调用 `read_task_context(task_id, sections)`。`databases` 是当前 Workspace 下所有 Project 有效授权的并集；其中 `database` 字段就是后续调用的 Workspace 唯一 mcp_alias，不传 Host、DSN、账号、密码或远端数据库名。
- 任务需要 Redis、MQ、ES、MinIO、任务调度或对象存储等中间件的实时连接、配置或故障排查信息时，必须优先调用 `read_middleware_context(task_id, environment?, components?, reveal_secrets?)`。显式环境读取该 Workspace 同名 Nacos 配置，省略时继承 task 环境。本机工具默认返回明文；需要脱敏视图时显式传 `reveal_secrets=false`。
- `read_task_context` 只负责数据库别名和通用环境 JSON，不是 Nacos 中间件实时信息的权威来源。
- Schema 不明确时先调用 `search_database_objects(task_id, database, object_type, pattern, detail, ...)`。优先使用 `names`，需要元数据时再升到 `summary`，只有确认目标后才用 `full`。
- 查询数据时调用 `execute_database_query(task_id, database, sql)`；只提交一条必要的只读 SQL。即使 SQL 自带 LIMIT，仍以服务端行数、字节数、超时和安全策略为准，并检查返回的 `truncated`。
- 数据查询或接口参数出现业务名称、ID、编码、编号时，在 prepare 后直接调用 `search_value_mappings`，不需要先读取数据库列表。命中已发布规则后直接调用 `resolve_value_candidates`，不再为确认映射来源调用 `read_task_context`、Schema 搜索或原始 SQL；只有没有合适映射时才进入这些探索链路。未指定 `interface_id` 的搜索不会返回接口绑定明细。需要“随机一个”时使用 `selection=random` 并把 `limit` 设为用户要求的数量，不再执行 `ORDER BY RAND()`。
- 不尝试写操作、跨库查询、外部表函数、文件/网络读取函数或调用方 SETTINGS。工具拒绝后应调整为更小、更明确的只读查询，而不是绕过策略。

## AI 标准执行流程

1. 先把用户的主意图声明给 `prepare_task_context`，创建一次任务，并在后续文档、数据库、接口、日志和运行操作中始终复用同一个 `task_id`。读取返回的 `execution_contract`；其中 `mutation_policy`、`required_steps` 和 `visualization_targets` 是当前任务的执行契约。
2. 根据任务意图选择最短的授权链路取证或修改；不要为了填充可视化页面调用无关工具。省略 `intent_type` 只用于兼容旧客户端，服务端会按 `task_execute` 处理并返回 warning。
3. 完成实际验证后，在最终回复用户前调用 `save_task_visualization_result`：阶段性且非终态使用 `investigating`；只有目标完成并至少有一项真实验证时使用 `resolved`；遇到明确阻塞时使用 `failed`，并记录根因和安全的下一步。
4. 结构化结论只保存脱敏摘要、工作空间相对代码位置、建议和验证结果，不保存凭据、原始日志或推测。保存记录不能替代给用户的最终答复。

### 意图路由

| intent_type | 执行要求 | 服务端可视化与约束 |
| --- | --- | --- |
| `interface_execute` | 搜索接口、按历史和映射组装参数、准备并执行只读计划 | 接口成功或失败都自动写接口可视化；没有真实执行记录不能标记 `resolved` |
| `data_query` | 业务值优先走现有映射；未命中时再定位关系表和 Schema，查询后调用 `save_data_visualization_query` | 初始化数据可视化查询条件；没有条件记录不能标记 `resolved` |
| `task_execute` | 按最短授权链路完成普通任务和验证 | 正常写任务可视化结论 |
| `bug_investigate` | 只查询和取证；有错误信号时检查当前 Workspace 已注册容器 | 禁止 `apply_workspace_changes` 和 `start_workspace`；确认真实错误才写日志可视化 |
| `bug_fix` | 有错误信号时先查注册容器，再修改、更新 Workspace 并验证 | 缺少日志检查或 Workspace 更新证据时不能标记 `resolved` |

主意图不排斥辅助链路：例如 `bug_fix` 可以同时查询数据或执行只读接口，并由实际工具调用分别生成数据或接口记录。MCP 只能阻止 Context Router 的运行写操作，不能拦截编码客户端自己的文件编辑能力，因此 `bug_investigate` 的只读要求还必须遵守返回的 `mutation_policy=forbidden`。

任务可视化详情中的“调用链路”只打开同一 `task_id` 的 Context Router MCP Trace；返回任务详情后仍保持原任务选择。系统中心的调用链路入口继续展示全部任务。

## 下一层文档

| document_id | 适用任务 |
| --- | --- |
| `context-router-prepare-guide` | 需要了解 prepare 参数、Workspace/active project 识别和返回范围 |
| `context-router-search-guide` | 需要按关键词定位文档、章节并理解相关度和索引错误 |
| `context-router-read-guide` | 需要了解批量文档、精确章节、顺序和 read_call_id |
| `context-router-trace-guide` | 需要理解 Tasks 页面记录了什么 |
| `context-router-routing-guide` | 需要按 startup/database/frontend/backend/business/debugging 路由 |

MCP 的 `tools/list` 固定为 22 个当前工具。识别出数据查询条件后，可调用 `save_data_visualization_query(task_id, description, database_key, schema_name, table_name, keyword)`；完成任务或形成阶段性结论后，调用 `save_task_visualization_result` 更新同一 task 的脱敏结构化结论。`resolved` 必须包含至少一项实际验证，`failed` 必须包含明确根因。Workspace、环境和来源由 task 绑定补全。排查 Docker 服务错误时，先调用 `list_task_containers(task_id, query?)` 识别当前任务 Workspace 已注册容器，再调用 `inspect_container_errors(task_id, container_id, since_minutes?, tail?, keywords?)`。第二个工具默认读取最近 15 分钟、最多 500 行，只在发现错误时保存日志可视化记录；未注册容器、不可访问日志、关键词不匹配或没有错误均不记录，调用方不得猜测容器 ID。数据查询和接口参数中的业务 ID 都优先按 `search_value_mappings -> resolve_value_candidates` 查询；接口转发按 `search_forwarding_interfaces`、可选 `read_forwarding_request_history`、`prepare_forwarding_request -> execute_forwarding_request` 执行。直接带可选 `environment` 的工具是 `prepare_task_context`、`read_middleware_context`、`resolve_value_candidates` 和 `prepare_forwarding_request`。
