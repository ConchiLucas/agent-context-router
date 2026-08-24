# Context Router MCP 使用说明

## AI 使用原则

- 新窗口遇到业务规则、启动、数据库或跨层链路任务时，调用 `prepare_task_context(task, cwd, agent_name)`。
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
- 不尝试写操作、跨库查询、外部表函数、文件/网络读取函数或调用方 SETTINGS。工具拒绝后应调整为更小、更明确的只读查询，而不是绕过策略。

## 下一层文档

| document_id | 适用任务 |
| --- | --- |
| `context-router-prepare-guide` | 需要了解 prepare 参数、Workspace/active project 识别和返回范围 |
| `context-router-search-guide` | 需要按关键词定位文档、章节并理解相关度和索引错误 |
| `context-router-read-guide` | 需要了解批量文档、精确章节、顺序和 read_call_id |
| `context-router-trace-guide` | 需要理解 Tasks 页面记录了什么 |
| `context-router-routing-guide` | 需要按 startup/database/frontend/backend/business/debugging 路由 |

MCP 的 `tools/list` 固定为 17 个当前工具。业务 ID 等参数可按 `search_value_mappings -> resolve_value_candidates` 显式查询，也可由接口准备阶段按绑定自动刷新；两条路径都只执行保存好的数据库别名、表字段和固定过滤，最多读取 10 个候选，不能传任意 SQL。接口转发按 `search_forwarding_interfaces -> prepare_forwarding_request -> execute_forwarding_request` 三步调用。地址、账号或角色省略时，准备阶段优先复用当前环境仍有效的最近成功选择，其次使用唯一候选；`selection_evidence` 会说明选择依据，只有无法可靠判断时才要求补选。普通请求保持默认 `value_strategy=reuse_successful`，复用最近成功日志；用户说“货主 ID 换一个”时使用 `refresh_selected` 和 `refresh_value_keys=["shipper_id"]`；用户说“所有业务值重新造数”时使用 `refresh_mapped`；只有明确说“不用历史”时才使用 `ignore_history`。调用方参数始终优先，定向刷新不会改变其他历史字段；无安全候选时返回 `needs_value_resolution`。执行只接受服务端短期计划及摘要，不接收任意 URL 或请求头，只允许明确分类为只读的接口。存在具备 `interface-forwarding` 能力的在线 Host Runner 时，执行会经单次短租约访问宿主机 VPN；否则使用容器内直连兼容路径。两条路径都执行相同的计划、配置指纹、响应上限和日志校验，账号请求头不会返回给 AI。c12-data 原始 Controller 接口当前不可执行，必须使用已登记的 MTP 包装接口。直接带可选 `environment` 的工具是 `prepare_task_context`、`read_middleware_context`、`resolve_value_candidates` 和 `prepare_forwarding_request`；prepare task 省略时使用 `local`，后三者省略时继承 task 环境，显式值必须与 task 一致。
