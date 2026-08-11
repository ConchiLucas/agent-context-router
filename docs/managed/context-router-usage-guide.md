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
- 任务需要 Redis、MQ、ES、MinIO、任务调度或对象存储等中间件的实时连接、配置或故障排查信息时，必须优先调用 `read_middleware_context(task_id, components, reveal_secrets)`，不要先从 application 配置、源码或通用环境 JSON 推断运行值。prepare 未传环境时读取 `default/local` Nacos 配置档，显式传 `test/uat` 时读取同名配置档。本机工具默认返回明文，当前授权任务可以直接返回和使用这些值；需要脱敏视图时显式传 `reveal_secrets=false`。不要把实际值写入源码、Markdown、持久化日志、无关工具参数或提交记录。
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

MCP 的 `tools/list` 固定为 `prepare_task_context`、`read_task_context`、`read_middleware_context`、`search_context_documents`、`read_context_document`、`search_database_objects`、`execute_database_query`、`apply_workspace_changes`、`start_workspace`、`get_workspace_operation`。某个 Workspace 当前没有有效数据库授权或 Nacos 配置档时，相关工具仍会存在，但只允许使用 task 绑定 Workspace 实际返回的能力，不能据此访问其他 Workspace 的资源。
