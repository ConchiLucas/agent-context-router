---
title: MCP 渐进式能力路由与 AI 开发执行链路技术方案
summary: 定义 Context Router 如何通过主意图、可叠加能力包、渐进工具发现和统一执行信封，稳定支持代码开发、Bug 排查与修复、数据查询、接口执行和 Workspace 运行任务。
---

# MCP 渐进式能力路由与 AI 开发执行链路技术方案

日期：2026-08-26  
状态：第一版已实现并通过真实 UAT MCP 链路验证  
适用客户端：Codex、Gemini CLI、Antigravity CLI、Cursor Agent、Grok CLI 及其他支持标准 MCP Streamable HTTP 的本机 AI Agent

## 实施状态（2026-08-26）

第一版已完成以下范围：

- 新增 `code_change` 主意图、任务执行硬约束和完成条件。
- 新增任务能力事件表与幂等能力修订，环境仍由 `task_id` 的不可变快照继承。
- `prepare_task_context` 支持只读 `capability_hints`，返回已启用能力与最多 5 个推荐动作。
- 新增 `discover_task_tools` 和 `invoke_task_tool`；发现结果包含完整输入/输出 Schema、参数说明、annotations、readiness、定义版本和可直接复用的调用信封。
- 统一调用入口复用现有专业工具处理器，并在追踪、数据库载荷和可视化链路中记录真实专业工具名。
- `execute_mapped_data_query` 区分主数据可视化与代码/Bug 任务的支撑证据，避免跨菜单污染。
- 现有专业工具暂时继续直出，作为 Codex、Gemini、Antigravity 灰度验证期兼容通道；确认三类客户端稳定后再执行本文的公共工具收敛阶段。

本设计完成时 MCP 工具数为 26（原 24 个加渐进式发现与统一调用两个入口）；后续接口意图详情工具上线后当前为 27 个，清单由运行时工具注册结果校验。

## 1. 背景

Context Router 当前已经形成一组覆盖面较完整的 MCP 能力，包括：

- Workspace 和 Project 上下文准备。
- Workspace 文档检索与按 ID 阅读。
- 任务环境和中间件上下文读取。
- 数据库目标解析、Schema 发现和有界只读 SQL。
- 表关联查询。
- 业务值映射和候选解析。
- 接口检索、历史复用、请求准备和受控执行。
- 数据、接口、日志和任务可视化。
- Workspace 代码变更应用、完整启动和异步运行状态查询。

本文编写前的旧基线在 `mcp_server.py` 中注册 24 个 MCP 工具，当前运行时为 27 个。数量和清单必须以代码注册表的校验结果为准，禁止继续手工维护多个不一致的工具列表。

现有问题不是单纯“工具 description 太短”，而是以下因素叠加：

1. 24 个工具一次性平铺给模型，多个工具在名称和使用场景上相似。
2. 全局 MCP Server instructions 同时描述数据、接口、日志、任务、运行等多条链路，关键优先级容易被埋没。
3. 部分工具参数只有类型、长度或枚举限制，缺少来源、条件必填、允许值语义和调用示例。
4. 当前 `intent_type` 把“最终要完成的目标”和“过程中需要调用的能力”混在一起，无法自然表达“Bug 修复需要数据库和接口取证”或“代码开发需要查询日志和中间件”。
5. 当前执行契约的 `required_steps` 偏向固定链路，容易被误解为严格状态机；如果服务端按固定顺序硬拦截，会降低 Agent 自主开发效率。
6. 客户端对动态 `tools/list_changed` 的支持和刷新时机不完全一致，不能把第一版渐进暴露建立在动态工具列表之上。

本方案将 MCP 定位为 AI 开发过程中的控制面与业务证据面，不把源码读取、代码编辑和普通开发命令代理到 MCP 后台。

## 2. 目标

### 2.1 产品目标

1. Agent 在任务开始时先明确用户最终目标，再获得最相关的少量 MCP 动作。
2. 数据查询、接口执行、日志、中间件、表关联等能力可以叠加到代码开发和 Bug 修复任务，不互相排斥。
3. 简单代码开发不因 MCP 路由增加明显调用负担。
4. 复杂 Bug 修复可以在一个 `task_id` 下完成日志、接口、数据库、源码、运行和验证闭环。
5. 服务端只强制 Workspace、环境、权限和安全边界，不强制无业务必要的调用顺序。
6. 工具 description、参数 Schema、结果和错误都能明确告诉模型“何时调用、如何调用、下一步是什么”。
7. 当前 24 个工具的服务实现全部复用，不因渐进暴露重写数据库、接口转发、日志或运行编排内核。
8. 调用链路和四类 AI 可视化继续保留真实动作证据，不因增加路由层而失真。

### 2.2 工程目标

1. 第一版继续使用无状态 Streamable HTTP，任务状态由显式 `task_id` 持久化。
2. 不依赖客户端动态刷新 `tools/list`。
3. 工具定义在代码中保持单一真源，description、输入 Schema、annotations、能力归属和处理器不能分散维护。
4. 公共 MCP 工具数量控制在 9 个左右，专业工具通过任务相关的动作发现结果渐进提供。
5. 明显场景由 `prepare_task_context` 直接返回推荐动作，不强制额外调用发现工具。
6. 所有专业动作继续复用原有 Pydantic/FastMCP 输入校验和业务 Service。

## 3. 非目标

本方案不实现以下内容：

- 不让 Context Router 代理 Agent 的文件读取、源码搜索、补丁编辑或 Git 操作。
- 不接收任意 Shell 命令，不把 Context Router 改造成远程代码执行平台。
- 不让 MCP 后台代替 Codex、Gemini 或 Antigravity 自身的推理与编码能力。
- 不开放数据库写入、DDL、跨库联邦查询或任意数据库连接参数。
- 不执行未导入、未授权或没有可用登记路由的业务接口；已导入接口不再按操作类型限制。
- 不读取未注册到当前 Workspace 的 Docker 容器。
- 不在第一版实现向量化工具搜索；24 个专业工具使用结构化标签、关键词和确定性排序即可。
- 不在第一版依赖 MCP Session 级动态工具列表或 `notifications/tools/list_changed`。
- 不在本方案中实现“已解决问题复用”；可以保留后续 TODO，但不进入本轮能力路由和执行闭环。
- 不因为增加路由层复制请求正文、响应正文、原始日志或数据库结果到新的持久化表。

## 4. 核心设计原则

### 4.1 最终目标与执行能力分离

任务模型必须区分：

```text
primary_intent = 用户最终想完成什么
capabilities   = 为完成目标允许或需要使用什么能力
stage          = 当前进行到哪个工作阶段
```

例如：

```json
{
  "primary_intent": "bug_fix",
  "capabilities": [
    "context.read",
    "logs.read",
    "database.read",
    "interface.read_execute",
    "code.modify",
    "runtime.execute"
  ],
  "stage": "investigating"
}
```

主意图不因为中途查询数据库或调用接口而变化。

### 4.2 能力只能叠加，不能用主意图永久隔离

- 初始能力由主意图、错误信号和 Agent 提供的能力提示确定。
- 只读能力可以在任务过程中按证据自动增加。
- 已增加的能力在同一 task 中保持可用，除非 Workspace、环境或授权失效。
- 主意图控制最终完成条件和修改权限，不控制所有可读工具的可见性。

### 4.3 MCP 是控制面，不是源码数据面

Agent 原生执行以下操作：

- 使用 `rg` 或客户端原生搜索能力定位源码。
- 阅读和编辑文件。
- 查看 Git diff。
- 按 Workspace 开发规范执行测试、lint 和 build。
- 结合代码语义决定修改方式。

Context Router MCP 只在以下关键节点介入：

- 建立任务、Workspace 和环境快照。
- 提供项目文档和业务上下文。
- 提供受约束的数据库、接口、日志、中间件和表关联证据。
- 应用 Workspace 代码变更或启动 Workspace。
- 提供运行状态和验证证据。
- 保存结构化任务结论。

### 4.4 安全约束硬执行，流程建议软执行

服务端硬性执行：

- task、Workspace、环境和 revision 一致性。
- Bug 查询的只读修改策略。
- 数据库只读、单语句、范围、行数、字节数和超时限制。
- 接口地址、方法、账号和请求计划安全。
- 注册容器边界。
- Workspace 变更路径边界和固定运行入口。
- `resolved` 必须引用真实成功验证调用。

服务端不得硬性要求：

- 每次开发必须读取全部文档。
- 每次数据库查询必须先探索 Schema。
- 每次接口调用必须查询数据库。
- 每次修改文件都立即应用 Workspace 变更。
- 每次测试都经过 MCP。
- 所有任务都按日志、数据库、接口、代码的固定顺序执行。
- 只读能力未在初始集合中就直接拒绝且不提供扩展路径。

### 4.5 推荐最短可靠链路

服务端推荐的不是“工具调用越多越完整”，而是“在安全约束内使用最少的真实证据完成任务”。

- 已发布映射命中时走原子映射执行，不重复探索 Schema。
- 已知接口和参数时直接准备请求，不重复搜索历史。
- 已知代码位置时直接阅读和修改，不强制文档搜索。
- 无运行时报错时不强制读取容器日志。
- 只有结果需要用户在数据可视化页面查看时才保存独立数据可视化记录。

## 5. 术语

| 术语 | 定义 |
| --- | --- |
| 主意图 | 用户最终希望完成的任务类型，决定终态和修改权限 |
| 能力 | 可在任务中使用的一组受控动作，例如数据库只读、接口计划执行 |
| 能力包 | 共享业务边界和启用规则的一组专业动作 |
| 公共工具 | 始终出现在 MCP `tools/list` 中的少量稳定工具 |
| 专业动作 | 当前 24 个工具中按任务需要渐进提供的领域动作 |
| 推荐动作 | prepare 或专业动作结果给出的下一步候选，包含完整输入 Schema |
| 动作发现 | 在任务出现新领域需求时查询相关专业动作 |
| 动作调用 | 通过统一公共工具执行一个已经发现或推荐的专业动作 |
| 阶段 | 用于展示和推荐排序的任务进度，不作为普通只读能力的严格状态机 |
| 执行证据 | 同一 task 下真实成功工具调用生成的 `tool_call_id` |

## 6. 主意图模型

### 6.1 主意图枚举

后续实现将现有枚举扩展为：

```text
interface_execute
data_query
task_execute
bug_investigate
bug_fix
code_change
```

语义如下：

| 主意图 | 最终目标 | 代码修改 |
| --- | --- | --- |
| `interface_execute` | 识别并实际执行一个已导入且路由可用的接口 | 禁止 |
| `data_query` | 获取业务数据或初始化数据可视化查询条件 | 禁止 |
| `task_execute` | 启动、重启、应用已存在变更或执行运行任务 | 按任务契约，不代表 Agent 编辑代码 |
| `bug_investigate` | 查询并解释问题，不实施修改 | 禁止 |
| `bug_fix` | 定位根因、修改代码、更新 Workspace 并验证 | 允许 |
| `code_change` | 开发功能、重构或完成普通代码修改并验证 | 允许 |

`task_execute` 不再承担普通代码开发的默认语义。用户要求新增功能、修改代码、重构、补测试时，Agent必须声明 `code_change`。

### 6.2 主意图来源

主意图由调用方 Agent 根据用户原始请求识别并显式提交。Context Router 不在本轮引入第二个大模型重复分类。

`prepare_task_context` 后续参数要求：

```json
{
  "task": "修复 UAT 合同分页接口查询不到数据的问题",
  "cwd": "/workspace/project",
  "environment": "uat",
  "intent_type": "bug_fix",
  "error_signal": true,
  "intent_summary": "定位接口返回空的根因，允许修改代码并验证",
  "capability_hints": ["logs", "interface", "database"]
}
```

规则：

- `intent_type` 在最终版本中必填，不再使用 `task_execute` 静默兼容缺失值。
- `capability_hints` 只影响推荐和初始只读能力，不直接授予修改或破坏性权限。
- `error_signal=true` 只允许用于 `bug_investigate` 或 `bug_fix`。
- 环境仍由 task 描述中的已登记别名或显式 `environment` 固化，后续工具不接受环境覆盖。

## 7. 能力模型

### 7.1 能力枚举

建议使用稳定的点分命名：

```text
context.read
task_context.read
middleware.read
relation.read
mapping.read
database.read
interface.read
interface.execute
logs.read
code.modify
runtime.execute
visualization.data.write
visualization.task.write
```

其中 `code.modify` 表示任务契约允许 Agent 使用自身工具修改当前 Workspace 代码，不代表 Context Router 提供任意文件写入工具。

### 7.2 当前工具归属

| 能力包 | 当前专业动作 |
| --- | --- |
| 核心任务 | `prepare_task_context` |
| 文档上下文 | `search_context_documents`、`read_context_document` |
| 任务环境 | `read_task_context`、`read_middleware_context` |
| 数据库 | `resolve_database_target`、`search_database_objects`、`execute_database_query` |
| 表关联 | `search_relation_tables`、`read_table_relations` |
| 业务值映射 | `search_value_mappings`、`resolve_value_candidates` |
| 数据可视化 | `execute_mapped_data_query`、`save_data_visualization_query` |
| 接口 | `search_forwarding_interfaces`、`read_forwarding_request_history`、`prepare_forwarding_request`、`execute_forwarding_request` |
| 日志 | `list_task_containers`、`inspect_container_errors` |
| Workspace 运行 | `apply_workspace_changes`、`start_workspace`、`get_workspace_operation` |
| 任务收口 | `save_task_visualization_result` |

### 7.3 初始能力矩阵

| 主意图 | 初始能力 | 按需扩展能力 |
| --- | --- | --- |
| `data_query` | context、mapping、data visualization | relation、database、task context |
| `interface_execute` | context、interface.read、interface.execute | mapping、database、request history |
| `bug_investigate` | context；有错误信号时增加 logs | relation、mapping、database、interface、middleware |
| `bug_fix` | context、code.modify、runtime；有错误信号时增加 logs | relation、mapping、database、interface、middleware |
| `code_change` | context、code.modify、runtime | relation、mapping、database、interface、logs、middleware |
| `task_execute` | context、runtime | logs、interface、database |

初始矩阵只影响推荐和动作发现排序。除修改和执行等受控能力外，只读能力允许按证据扩展。

## 8. 渐进式暴露总体架构

### 8.1 第一版选择

第一版采用“固定公共工具 + 任务相关专业动作”的方式，不使用动态 `tools/list_changed`：

```text
MCP tools/list
  └─ 固定返回少量公共工具
       ├─ prepare_task_context
       ├─ search_context_documents
       ├─ read_context_document
       ├─ discover_task_tools
       ├─ invoke_task_tool
       ├─ apply_workspace_changes
       ├─ start_workspace
       ├─ get_workspace_operation
       └─ save_task_visualization_result

prepare / discover / action result
  └─ 只返回当前任务相关的 3～8 个专业动作定义
       ├─ action name
       ├─ title
       ├─ discriminative description
       ├─ input schema
       ├─ annotations
       ├─ readiness
       ├─ reason
       └─ recommended arguments
```

这样能够真实减少初始工具列表，又不要求客户端在同一连接中刷新工具定义。

### 8.2 为什么公共工具中保留运行编排

`apply_workspace_changes`、`start_workspace`、`get_workspace_operation` 和 `save_task_visualization_result` 保持直接可见，原因是：

- 它们属于代码开发、Bug 修复和运行任务的稳定主链路。
- 名称和职责区分明确，不是当前工具误选的主要来源。
- 隐藏这些工具会让简单代码开发多一次发现调用。
- 服务端已经具备 Workspace、路径、运行配置和任务契约硬校验，直接可见不会扩大任意命令执行边界。

### 8.3 专业动作不删除

当前专业工具的业务处理函数全部保留，但不再逐个注册到最终公共 `tools/list`。它们改为注册进服务端 `TaskToolRegistry`，由 `invoke_task_tool` 调用。

专业动作仍然拥有：

- 原工具名。
- 原输入 Pydantic Schema。
- 原业务 Service。
- 原 annotations。
- 原工具级审计摘要和 payload 策略。
- 原可视化副作用。
- 原安全限制。

渐进暴露只改变发现和分发，不改变数据库、接口、日志或运行内核。

### 8.4 不强制每次发现

`discover_task_tools` 是兜底，不是每次动作调用的必经步骤。

调用方可以在以下来源获得专业动作定义：

1. `prepare_task_context.recommended_actions`。
2. 上一个专业动作返回的 `next_actions`。
3. `discover_task_tools` 主动搜索结果。
4. 同一 task 中之前已经返回过且 definition revision 未变化的动作缓存。

Agent 已经拥有动作 Schema 时，直接调用 `invoke_task_tool`，不重复发现。

## 9. 专业动作注册表

### 9.1 单一真源

新增代码级 `TaskToolRegistry`，每个动作使用统一定义：

```python
TaskToolDefinition(
    name="execute_mapped_data_query",
    title="按业务映射查询并保存数据可视化",
    capability="database.read",
    description="...",
    input_model=ExecuteMappedDataQueryInput,
    output_model=ExecuteMappedDataQueryOutput,
    annotations=ToolAnnotations(...),
    prerequisites=("task.prepared", "mapping.published"),
    handler=execute_mapped_data_query_handler,
    keywords=("数据查询", "业务值", "ID", "编码", "随机"),
    priority_by_intent={"data_query": 100, "interface_execute": 30},
)
```

同一份定义用于：

- MCP动作发现。
- 统一动作调用校验。
- 系统文档工具说明页。
- MCP接入面板。
- description/Schema lint。
- E2E 工具命中率测试。

### 9.2 动作检索排序

第一版不使用向量模型，使用确定性评分：

```text
主意图默认优先级
+ 已启用能力加权
+ capability hint 加权
+ 动作名称/标题/关键词精确匹配
+ 中文子串匹配
+ 前一步 next_actions 加权
+ readiness 加权
- 缺少前置条件降权
- 与 mutation_policy 冲突直接过滤
```

返回稳定排序和 `match_reasons`，同样输入必须得到同样结果。

### 9.3 动作定义版本

注册表计算稳定 `definition_revision`：

- 基于动作名、description、输入 JSON Schema、输出 JSON Schema 和 annotations 计算 SHA-256。
- prepare 和 discover 返回 revision。
- `invoke_task_tool` 可选接收调用方缓存的 revision。
- revision 不一致时返回 `tool_definition_changed` 和最新定义，不执行旧参数。

## 10. 公共 MCP 工具契约

### 10.1 `prepare_task_context`

保留现有 Workspace、Project、文档投影、环境快照和 task 创建逻辑，扩展输入：

```json
{
  "task": "修复 UAT 合同分页接口返回空的问题",
  "cwd": "/workspace/c12-mtp",
  "intent_type": "bug_fix",
  "error_signal": true,
  "intent_summary": "定位根因、允许修改并完成接口验证",
  "environment": "uat",
  "capability_hints": ["logs", "interface", "database"]
}
```

扩展输出：

```json
{
  "task_id": 952,
  "environment": {
    "key": "uat",
    "revision": 8,
    "selection": "task_explicit"
  },
  "execution_contract": {
    "primary_intent": "bug_fix",
    "mutation_policy": "allowed",
    "hard_requirements": [
      "attempt_registered_error_log_inspection_before_apply_when_error_signal"
    ],
    "completion_requirements": [
      "workspace_changes_applied",
      "verified_outcome",
      "task_result_saved"
    ]
  },
  "enabled_capabilities": [
    "context.read",
    "logs.read",
    "code.modify",
    "runtime.execute"
  ],
  "recommended_actions": [
    {
      "name": "list_task_containers",
      "reason": "任务包含实际运行错误信号，先定位已注册容器",
      "readiness": "ready",
      "input_schema": {},
      "recommended_arguments": {"task_id": 952},
      "definition_revision": "sha256"
    }
  ],
  "documents": {},
  "warnings": []
}
```

约束：

- 推荐动作最多 5 个。
- prepare 不执行专业动作。
- prepare 不返回数据库连接信息、接口请求头或日志正文。
- `hard_requirements` 与普通推荐步骤分开，不能继续用一个 `required_steps` 同时表达两种语义。

### 10.2 `discover_task_tools`

用途：任务中出现新领域需求时，发现相关专业动作。

输入：

```json
{
  "task_id": 952,
  "query": "确认合同数据是否存在并检查分页SQL字段",
  "capability_hints": ["database", "relation"],
  "limit": 5
}
```

规则：

- `task_id` 必须存在且环境 revision 仍有效。
- `query` 必填，最大 500 字符。
- `capability_hints` 可选，只影响排序。
- `limit` 为 1～8，默认 5。
- 禁止返回与当前 task mutation policy 冲突的写动作。
- 可返回尚缺前置条件的动作，但必须明确 `readiness` 和缺失内容。

输出：

```json
{
  "task_id": 952,
  "query": "确认合同数据是否存在并检查分页SQL字段",
  "enabled_capabilities": ["database.read", "relation.read"],
  "actions": [
    {
      "name": "search_value_mappings",
      "title": "搜索已发布业务值映射",
      "description": "...",
      "capability": "mapping.read",
      "readiness": "ready",
      "match_reasons": ["命中业务数据查询意图", "查询包含合同业务词"],
      "input_schema": {},
      "annotations": {},
      "recommended_arguments": {
        "task_id": 952,
        "query": "合同"
      },
      "definition_revision": "sha256"
    }
  ]
}
```

只读能力在成功发现时可以自动加入 task capability events；写能力只能由主意图契约授予。

### 10.3 `invoke_task_tool`

用途：调用一个已经推荐或发现的专业动作。

输入：

```json
{
  "task_id": 952,
  "tool_name": "search_value_mappings",
  "arguments": {
    "query": "合同"
  },
  "definition_revision": "sha256"
}
```

规则：

- 外层 `task_id` 是唯一任务归属；`arguments` 不重复传 `task_id`，分发器在校验后注入。
- `tool_name` 必须存在于注册表，不能调用任意 Python 函数或任意 MCP Server。
- `arguments` 必须通过目标动作原 Pydantic Schema 校验。
- 调用方必须已经获得该动作定义，或目标动作属于当前 task 已启用能力；否则返回最新定义和发现提示，不直接执行。
- `definition_revision` 必须匹配当前动作定义。
- 目标动作的所有原安全校验继续执行。
- 不允许在 arguments 中覆盖环境、Workspace、数据库连接、接口 URL、请求头或容器范围。

成功输出统一包裹原结果：

```json
{
  "task_id": 952,
  "tool_call_id": 12031,
  "tool_name": "search_value_mappings",
  "capability": "mapping.read",
  "status": "succeeded",
  "result": {},
  "workflow": {
    "stage": "gathering_evidence",
    "workflow_complete": false,
    "next_actions": [
      {
        "name": "execute_mapped_data_query",
        "reason": "已找到精确发布映射",
        "input_schema": {},
        "recommended_arguments": {
          "mapping_id": "...",
          "description": "查询合同数据"
        }
      }
    ]
  }
}
```

### 10.4 公共运行工具

以下工具继续直接注册并保持现有参数：

- `apply_workspace_changes`
- `start_workspace`
- `get_workspace_operation`
- `save_task_visualization_result`

它们仍应返回统一 `workflow` 块，但不需要经 `invoke_task_tool` 二次分发。

## 11. 统一结果和错误信封

### 11.1 成功结果

所有公共工具和专业动作统一返回：

```json
{
  "status": "succeeded",
  "tool_call_id": 12031,
  "result": {},
  "workflow": {
    "stage": "verifying",
    "workflow_complete": false,
    "next_actions": [],
    "expanded_capabilities": [],
    "warnings": []
  }
}
```

原有业务结果放入 `result`，避免不同工具把下一步提示散落在不同字段。

### 11.2 参数错误

参数错误必须可重试：

```json
{
  "status": "error",
  "error": {
    "code": "missing_required_arguments",
    "message": "execute_database_query 缺少必填参数 sql",
    "missing": ["sql"]
  },
  "retry": {
    "tool_name": "execute_database_query",
    "input_schema": {},
    "recommended_arguments": {
      "database_context_id": "复用 resolve_database_target 的原值",
      "sql": "只读 SELECT，必须有界"
    }
  }
}
```

### 11.3 能力未启用

只读动作不能只返回拒绝，必须提供扩展路径：

```json
{
  "status": "error",
  "error": {
    "code": "capability_not_enabled",
    "message": "当前任务尚未启用 database.read"
  },
  "retry": {
    "tool_name": "discover_task_tools",
    "recommended_arguments": {
      "task_id": 952,
      "query": "查询当前问题涉及的数据库数据",
      "capability_hints": ["database"]
    }
  }
}
```

如果动作本身已由 prepare 或上一步明确推荐，则调用时自动启用相应只读能力，不要求重复 discover。

## 12. 工具 description 与 Schema 规范

### 12.1 description 结构

每个专业动作 description 使用统一结构：

```text
【能力域 · 优先级】一句话定位。
何时使用：明确触发场景。
前置条件：参数或上一步来源。
不要使用：最容易混淆的相邻工具和例外。
成功结果：返回什么以及是否产生可视化。
下一步：正常成功后的推荐动作。
```

description 不追求无限加长，重点是区分度。全局 Server instructions 只保留跨工具的稳定规则，具体业务顺序放回各动作定义和结构化 `next_actions`。

### 12.2 参数说明规范

所有公开参数必须具有非空 `description`，至少说明：

- 参数业务含义。
- 值从哪里取得，是否允许调用方构造。
- 条件必填关系。
- 枚举每个值的差异。
- 默认值行为。
- 一个短示例或反例。

示例：

```text
database_context_id:
当前 task 下由 resolve_database_target 返回的 36 位不透明 ID；必须原样复用，
禁止把数据库别名、数据库名称或其他 task 的 ID 传入。

detail_level:
names=仅名称，summary=名称与关键元数据，full=完整字段/索引元数据；
仅允许这三个值，不存在 columns。

sql:
必填，只允许一条有界只读 SELECT/SHOW/EXPLAIN；不得为空、不得多语句，
数据库目标由 database_context_id 决定。
```

### 12.3 自动质量门禁

CI 增加工具定义 lint：

- 每个动作有 title、description、input schema、output schema 和 annotations。
- 每个参数有 description。
- description 引用的工具名必须存在于注册表。
- `next_actions` 引用的动作必须存在。
- 枚举值必须在参数说明中完整出现。
- 只读动作必须声明 `readOnlyHint=true`。
- 非幂等和可能有破坏性的动作必须显式标记。
- 注册表动作名全局唯一。
- 系统文档展示的工具数量由注册表生成，不允许手写常量。

## 13. 任务阶段模型

阶段用于推荐、时间线和完成度，不作为普通只读调用的硬拦截：

```text
prepared
gathering_context
investigating
designing
modifying
verifying
applying
resolved
failed
```

允许的常见转换：

```text
prepared -> gathering_context -> investigating/designing
investigating -> modifying
designing -> modifying
modifying -> verifying
verifying -> modifying       # 验证失败继续修复
verifying -> applying
applying -> verifying        # 部署后真实验证
verifying -> resolved
任意非终态 -> failed         # 仅具体阻塞
```

以下行为合法：

- 在 `modifying` 阶段补查数据库或接口历史。
- 在 `verifying` 阶段重新阅读代码和继续修改。
- 在 `applying` 失败后回到 `modifying`。
- 在没有运行时报错时跳过 `logs.read`。

## 14. 代码开发链路

### 14.1 快速链路

适用于明确、局部、无需业务系统取证的代码修改：

```text
prepare_task_context(code_change)
  -> Agent 原生搜索和阅读代码
  -> Agent 原生修改代码
  -> Agent 按项目规范执行 Docker test/lint/build
  -> apply_workspace_changes(一次提交全部实际变更路径)
  -> get_workspace_operation(轮询到终态)
  -> save_task_visualization_result(resolved + verification_call_ids)
```

要求：

- prepare 后不强制读取文档；目标明确时可以直接定位源码。
- 源码读取、编辑和本地测试不经过 MCP。
- `apply_workspace_changes` 在一轮修改和本地验证完成后调用一次，不按文件调用。
- 除异步状态轮询外，简单任务目标为 4～6 次 MCP 调用。

### 14.2 需要业务证据的代码开发

例如“给班列详情增加承运商名称并验证 UAT 数据”：

```text
prepare(code_change, uat, hints=[relation,database,interface])
  -> read_table_relations / search_value_mappings
  -> 必要时 execute_mapped_data_query 或原始只读查询
  -> 搜索接口定义或读取最近成功请求
  -> Agent 原生修改代码
  -> Agent 原生执行测试
  -> apply_workspace_changes
  -> get_workspace_operation
  -> execute_forwarding_request 验证接口
  -> 必要时数据库交叉验证
  -> save_task_visualization_result
```

数据和接口能力是 `code_change` 的辅助能力，不改变主意图，也不新建 task。

### 14.3 代码开发完成条件

`code_change` 标记 `resolved` 至少满足：

- 有实际修改路径。
- `apply_workspace_changes` 成功，或者任务明确不需要运行编排且有其他有效验证策略；后一种情况必须由执行契约显式允许。
- 至少一个真实成功验证调用或可审计的运行操作。
- 任务结论保存成功。

## 15. Bug 修复链路

### 15.1 有运行时错误信号

```text
prepare_task_context(bug_fix, error_signal=true)
  -> list_task_containers
  -> inspect_container_errors
  -> 按错误证据扩展 database/interface/middleware/relation
  -> Agent 原生定位和修改源码
  -> Agent 原生执行本地验证
  -> apply_workspace_changes
  -> get_workspace_operation
  -> 复用原问题入口进行真实验证
  -> 必要时再次检查日志
  -> save_task_visualization_result(resolved)
```

硬要求：

- `error_signal=true` 时，在第一次 `apply_workspace_changes` 之前必须记录一次当前 task 注册容器的解析和错误检查尝试；找到可访问容器时必须完成有界日志检查，没有注册容器或日志不可访问时以客观 unavailable 结果满足“已尝试”要求，不能伪造错误证据，也不能只因日志不可见永久卡死修复链路。
- 未找到错误日志不是伪造日志记录的理由；服务端不生成空日志可视化。
- 容器不可见或 Host Runner 不可用时，继续允许代码和其他只读证据排查，但最终结论必须说明日志证据缺失；是否允许修改由具体 blocker 和已有证据决定，不因工具不可见自动伪造成功。

### 15.2 无运行时错误信号

适用于页面展示错误、字段缺失、计算错误、分页不正确、交互异常等：

```text
prepare_task_context(bug_fix, error_signal=false)
  -> 复现问题或读取相关代码
  -> 按需查询接口、数据库、表关系或中间件
  -> 确认根因
  -> 修改代码并本地验证
  -> apply_workspace_changes
  -> get_workspace_operation
  -> 使用原问题入口验证
  -> save_task_visualization_result
```

这类任务不强制读取 Docker 日志。

### 15.3 原问题入口验证

修复后优先复用修复前的验证入口：

| Bug 类型 | 修复后验证 |
| --- | --- |
| 接口错误 | 相同 Workspace、环境、接口、账号角色和业务参数重新执行 |
| 数据错误 | 相同业务条件重新查询数据库或映射 |
| 容器异常 | 查看新时间窗口日志，确认错误不再出现 |
| 中间件错误 | 验证当前 task 环境的真实组件状态和业务结果 |
| 页面错误 | 使用浏览器复现原交互和边界状态 |
| 代码逻辑错误 | 单元测试、集成测试、构建和相关回归 |

### 15.4 Bug 修复完成条件

`bug_fix` 标记 `resolved` 至少满足：

- 根因有实际证据，不是纯推测。
- 有真实代码修改并成功应用 Workspace 变更。
- 有修复后验证证据。
- 有错误信号时满足日志检查硬要求。
- 任务结论保存成功。

验证失败时在同一个 task 下回到 `investigating` 或 `modifying`，不重新 prepare，除非环境 revision 已变化。

## 16. Bug 查询链路

`bug_investigate` 与 `bug_fix` 共享读取能力，但 mutation policy 为 `forbidden`：

```text
prepare(bug_investigate)
  -> 按需读取日志、接口、数据库、中间件、表关系和源码
  -> 保存证据和根因分析
  -> save_task_visualization_result(resolved/failed)
```

服务端必须拒绝：

- `apply_workspace_changes`
- `start_workspace`
- 任何未来新增的代码或配置修改动作

MCP 无法阻止客户端绕过 MCP 直接编辑文件，因此只读保证还需要 Workspace 根 `AGENTS.md` 和客户端任务规则明确约束。调用链路应把违反契约的 MCP 尝试记录为拒绝事件。

## 17. 数据、接口和运行任务链路

### 17.1 数据查询

```text
prepare(data_query)
  -> search_value_mappings
  -> 命中：execute_mapped_data_query（查询和数据可视化原子完成）
  -> 未命中：resolve_database_target
              -> search_database_objects（仅结构不确定时）
              -> execute_database_query
              -> 需要页面展示时 save_data_visualization_query
  -> save_task_visualization_result
```

### 17.2 接口执行

```text
prepare(interface_execute)
  -> search_forwarding_interfaces
  -> 按需 read_forwarding_request_history
  -> prepare_forwarding_request
  -> 缺业务参数时扩展 mapping/database
  -> execute_forwarding_request
  -> save_task_visualization_result
```

### 17.3 运行任务

```text
prepare(task_execute)
  -> start_workspace 或 apply_workspace_changes
  -> get_workspace_operation
  -> 失败时按需扩展 logs
  -> save_task_visualization_result
```

这些链路保持现有能力，渐进路由不得为了代码开发而降低数据、接口或运行任务的直接性。

## 18. 跨能力扩展规则

### 18.1 扩展触发来源

能力扩展来源包括：

1. prepare 输入中的 `capability_hints`。
2. 专业动作结果中的结构化 `expand_capabilities`。
3. Agent 主动调用 `discover_task_tools`。
4. 服务端根据明确业务状态自动扩展，例如接口参数存在已发布映射绑定。

禁止仅凭宽泛自然语言做破坏性能力授权。

### 18.2 常见跨能力关系

| 当前能力 | 触发条件 | 扩展能力 |
| --- | --- | --- |
| logs | 日志包含 SQL、表名或数据库连接错误 | database、relation、middleware |
| interface | 请求缺少业务 ID 或编码 | mapping、database |
| database | 查询结果与接口返回不一致 | interface、logs |
| relation | 需要验证真实业务数据 | database |
| code_change | 代码依赖业务表、接口或中间件 | relation、database、interface、middleware |
| runtime | 启动失败或健康检查失败 | logs、interface |

### 18.3 同一 task 继承规则

扩展能力必须继续使用：

- 同一个 `task_id`。
- 同一个 Workspace 快照。
- 同一个环境 key 和 revision。
- 同一个 Agent 来源。
- 同一个 mutation policy。

不允许因为扩展数据库或接口能力而重新选择环境、数据库或账号范围。

## 19. 可视化记录策略

### 19.1 总体原则

一次主任务可以产生多类可视化记录，但辅助能力不能改变主任务类型。

| 真实动作 | 可视化行为 |
| --- | --- |
| 从注册容器确认错误 | 自动创建或更新日志可视化 |
| 实际执行接口 | 自动创建接口可视化记录 |
| 用户明确要求展示查询条件/结果 | 创建数据可视化 |
| 仅用于代码修复的内部数据库证据 | 默认只关联 task 工具证据，不强制创建独立数据卡片 |
| 任务形成阶段或最终结论 | 更新任务可视化 |

### 19.2 原子映射查询的用途标记

现有 `execute_mapped_data_query` 会原子保存数据可视化。为兼容 Bug 修复和代码开发的辅助查询，后续输入增加服务端枚举：

```text
purpose=primary_visualization
purpose=supporting_evidence
```

- `data_query` 默认 `primary_visualization`。
- `bug_fix`、`code_change` 默认 `supporting_evidence`。
- supporting evidence 仍保存工具调用和有界执行摘要，但不创建独立数据可视化记录。
- 用户明确要求在页面查看时可以使用 `primary_visualization`。

这避免代码开发中每次查数据都污染数据可视化列表。

## 20. 执行契约改造

现有 `TaskExecutionContract.required_steps` 需要拆分为：

```json
{
  "primary_intent": "bug_fix",
  "mutation_policy": "allowed",
  "hard_requirements": [],
  "completion_requirements": [],
  "recommended_flow": [],
  "visualization_policy": {}
}
```

语义：

- `hard_requirements`：服务端必须验证的安全或证据边界。
- `completion_requirements`：保存 `resolved` 之前必须满足的事实。
- `recommended_flow`：给 Agent 的最短建议，不作为普通调用硬拦截。
- `visualization_policy`：哪些真实动作自动落哪类可视化。

不得继续用一个字符串数组同时表达推荐步骤、权限和完成条件。

## 21. 持久化设计

### 21.1 `mcp_tasks` 扩展

建议增加：

```text
workflow_stage           VARCHAR(32) NOT NULL DEFAULT 'prepared'
capability_revision      INTEGER NOT NULL DEFAULT 1
execution_contract_json  JSONB NOT NULL
```

`intent_type` 增加 `code_change` 检查约束。

`execution_contract_json` 保存 prepare 时生成的不可变契约快照，后续代码规则变化不重写历史 task。

### 21.2 `mcp_task_capability_events`

新增能力事件表：

```text
id                  BIGINT IDENTITY PRIMARY KEY
task_id             BIGINT NOT NULL REFERENCES mcp_tasks(id) ON DELETE CASCADE
capability          VARCHAR(64) NOT NULL
event_type          VARCHAR(16) NOT NULL  # enabled / observed
source              VARCHAR(32) NOT NULL  # prepare / hint / tool_result / discovery / system
reason_code         VARCHAR(64) NOT NULL
evidence_call_id    BIGINT NULL REFERENCES mcp_tool_calls(id) ON DELETE SET NULL
revision            INTEGER NOT NULL
created_at          TIMESTAMPTZ NOT NULL
```

能力以追加事件记录，不做可变 JSON 数组覆盖。当前有效能力由任务初始集合加 enabled events 聚合。

第一版不支持普通业务过程主动禁用能力；Workspace、环境或授权失效由原有实时校验处理。

### 21.3 工具定义不入库

专业动作 description、Schema 和 handler 不写 PostgreSQL，以代码注册表为真源。数据库只保存：

- task 得到过哪些动作推荐。
- 实际调用了哪个动作。
- 能力如何扩展。
- 工具定义 revision。

### 21.4 推荐动作记录

可以在现有 `mcp_tool_calls` 结果摘要中保存推荐动作数量和名称；不保存完整 Schema 副本。若需要审计模型看到的定义，仅保存 definition revision，历史定义由 Git 版本追溯。

## 22. 调用链路与审计

### 22.1 路由调用记录

客户端实际调用的是 `invoke_task_tool`，业务动作可能是 `execute_database_query`。调用链必须同时保留：

```text
transport_tool_name = invoke_task_tool
resolved_tool_name  = execute_database_query
capability          = database.read
definition_revision = sha256
```

推荐在同一个 `mcp_tool_calls` 节点增加上述字段，不为一次业务动作创建两个并列节点，避免时间线翻倍。

页面显示：

```text
执行数据库只读查询
invoke_task_tool → execute_database_query
```

### 22.2 工具证据 ID

- `invoke_task_tool` 返回的 `tool_call_id` 就是本次真实业务动作的证据 ID。
- `save_task_visualization_result.verification_call_ids` 继续引用它。
- 服务端验证 `resolved_tool_name` 和调用状态，不把只完成路由但业务失败的节点当作验证成功。

### 22.3 敏感信息

路由层不得扩大记录内容：

- 不记录中间件明文配置。
- 不记录接口请求头。
- 不记录数据库连接值。
- 不把原始 SQL、结果集、响应正文或日志正文复制到能力事件表。
- 继续复用现有白名单 payload、脱敏摘要和过期策略。

## 23. 性能设计

### 23.1 调用次数目标

| 场景 | 目标 MCP 调用量，不含必要轮询 |
| --- | --- |
| 简单代码修改 | 4～6 次 |
| 普通代码开发并运行 | 5～8 次 |
| 无运行日志的 Bug 修复 | 6～10 次 |
| 涉及日志、数据库和接口的复杂 Bug | 9～15 次 |
| 直接业务数据查询 | 3～5 次 |
| 参数完整的接口执行 | 4～6 次 |

调用量是优化指标，不是硬性失败条件。

### 23.2 避免额外发现调用

- prepare 直接返回最多 5 个推荐动作。
- 每个动作结果直接返回最多 3 个 next actions。
- 同一 task 内缓存已见动作定义。
- `discover_task_tools` 只在任务跨入新领域或 AI 不确定工具时调用。
- 映射执行、接口准备和日志提取继续使用现有原子服务，不拆成更多微工具。

### 23.3 服务端开销

- `TaskToolRegistry` 常驻内存，动作发现不访问外部网络。
- task 能力聚合按 `task_id + capability_revision` 缓存。
- capability event 写入失败不得放行不满足权限的动作。
- description 和 JSON Schema 在进程启动时生成并缓存。
- 推荐排序使用确定性本地计算，不调用大模型。

## 24. 安全边界

### 24.1 Workspace 和环境

- 所有专业动作从 `task_id` 解析 Workspace 和环境。
- `invoke_task_tool.arguments` 不接受 Workspace ID、环境、数据库连接、接口基础 URL 或容器范围覆盖。
- 环境 revision 变化后返回 `environment_changed`，要求重新 prepare。

### 24.2 数据库

- 继续使用 `database_context_id` 短期句柄。
- 只允许受支持 Connector 的只读授权。
- 保留 SQL 解析、单语句、跨库拒绝、行数、字节数和超时边界。
- 能力路由不能绕过 `DatabaseContextService` 和 `DatabaseQueryService`。

### 24.3 接口

- 只执行导入接口和服务端准备的短期不可变计划。
- 不允许 raw URL、method、header 或 arbitrary override。
- 继续由服务端注入账号请求头并通过 Host Runner 访问需要 VPN 的地址。
- `interface.execute` 授予已导入、路由可用且通过短期计划固化的接口执行能力，不限制 operation_kind。

### 24.4 日志

- 先从 task 注册容器列表选择。
- 保留时间、行数、字节数、非 follow 和脱敏限制。
- 无可访问日志或无错误证据时不创建日志可视化。

### 24.5 代码和运行

- Context Router 不接收任意代码补丁或 Shell。
- `apply_workspace_changes` 只接收实际 Workspace 相对变更路径。
- `start_workspace` 和 apply 只执行已登记、物化并校验的固定运行配置。
- `bug_investigate` 的 mutation policy 必须拒绝运行写动作。

## 25. 错误模型

新增或统一以下错误码：

```text
intent_required
intent_not_supported
capability_hint_not_supported
capability_not_enabled
tool_not_found
tool_not_recommended
tool_definition_changed
tool_arguments_invalid
tool_prerequisite_missing
mutation_forbidden
hard_requirement_missing
completion_requirement_missing
environment_changed
workspace_changed
verification_missing
```

每个错误必须包含：

- 稳定 `code`。
- 简洁中文 `message`。
- `retryable`。
- 缺失条件或错误参数路径。
- 可执行的 `retry` 或 `next_actions`。

不得只返回一段无法自动恢复的自然语言错误。

## 26. 模块设计

后续实现建议新增或调整：

```text
backend/src/context_router/
├── mcp_server.py
├── mcp_tool_registry.py                 # 专业动作单一注册表
├── schemas/
│   ├── context.py                       # 主意图、执行契约、prepare 扩展
│   └── task_tools.py                    # discover/invoke/统一结果信封
├── services/
│   ├── task_intent.py                   # 主意图与契约构建
│   ├── task_capability.py               # 初始能力、扩展和有效能力聚合
│   ├── task_tool_discovery.py            # 确定性动作检索和排序
│   ├── task_tool_invocation.py           # Schema 校验、分发和结果标准化
│   └── task_workflow.py                  # 阶段、完成条件和 next actions
├── repositories/
│   ├── task_repository.py
│   └── task_capability_repository.py
└── services/mcp_trace.py                # transport/resolved tool 审计

backend/migrations/versions/
└── <revision>_add_progressive_task_capabilities.py
```

现有数据库、接口、映射、日志、任务可视化和运行 Service 不迁移业务逻辑，只通过适配器注册为专业动作。

## 27. 实施阶段

### 阶段一：工具定义规范化，不改变公开工具列表

1. 建立 `TaskToolRegistry`，先以 shadow 模式注册当前 24 个工具。
2. 为每个工具和参数补全 description、输入 Schema、输出 Schema 和 annotations。
3. 增加定义 lint 和工具数量自动生成。
4. 增加统一错误结构，但保持原工具仍可直接调用。
5. 建立真实中文任务命中率基线。

目的：先改善参数准确率，并证明注册表与现有处理器完全一致。

### 阶段二：引入主意图和能力模型

1. 增加 `code_change`。
2. 拆分 hard requirements、completion requirements 和 recommended flow。
3. 增加 capability events 和 task workflow stage。
4. prepare 返回 enabled capabilities 和 recommended actions。
5. 保持现有工具直接调用，验证新模型不影响业务结果。

### 阶段三：增加渐进发现和统一动作调用

1. 增加 `discover_task_tools`。
2. 增加 `invoke_task_tool`。
3. 专业动作通过注册表调用原处理器。
4. Trace 增加 transport/resolved tool 字段。
5. 完成 Codex、Gemini、Antigravity 真实 E2E。

### 阶段四：切换最终公共工具面

1. `tools/list` 只保留 9 个公共工具。
2. 专业工具不再直接注册到公共 MCP 列表。
3. 更新系统文档、接入测试和 MCP 配置说明。
4. 重启后要求三个当前客户端重新加载 MCP 工具定义。
5. 不长期保留重复的直接工具兼容入口，避免重新回到平铺工具问题。

### 阶段五：评估是否需要语义工具搜索

只有满足以下任一条件才引入关键词索引增强或向量检索：

- 专业动作超过 40～50 个。
- 确定性搜索 Top 5 命中率低于验收目标。
- 多个外部 MCP Server 被接入同一 Context Router。

当前 24 个动作不需要先引入向量基础设施。

## 28. 测试方案

### 28.1 单元测试

- 主意图到初始能力矩阵。
- `code_change` mutation policy。
- Bug error signal 硬要求。
- 只读能力追加和幂等事件。
- 动作注册表唯一性和 definition revision。
- 工具 description 和参数 description lint。
- 动作检索排序与中文子串匹配。
- invoke 参数注入、Schema 校验和 handler 分发。
- 统一成功/错误信封。
- completion requirements 判定。

### 28.2 集成测试

- prepare 返回正确 Workspace、环境、主意图、能力和推荐动作。
- prepare 推荐动作可不经 discover 直接 invoke。
- discover 扩展数据库、接口、日志、中间件和表关联能力。
- invoke 完整复用原数据库、接口、日志和可视化 Service。
- bug_investigate 拒绝 apply/start。
- bug_fix 有错误信号但未检查日志时拒绝首次 apply。
- bug_fix 无错误信号时允许跳过日志。
- code_change 可以在修改前后任意补充只读证据。
- 环境 revision 变化后所有领域动作一致失败。
- supporting evidence 不污染数据可视化列表。
- 路由 Trace 只产生一个业务节点并正确保存 resolved tool。

### 28.3 MCP E2E

每个客户端至少覆盖：

1. 简单代码修改。
2. 需要表关系和数据库证据的代码开发。
3. 有容器错误、数据库和接口验证的 Bug 修复。
4. 只查询不修改的 Bug 排查。
5. 直接数据查询。
6. 直接接口执行。
7. Workspace 启动与失败日志排查。

客户端：

- Codex
- Gemini CLI
- Antigravity
- Cursor Agent
- Grok CLI

### 28.4 安全回归

- 跨 task 的 database_context_id。
- 调用方伪造环境和 Workspace。
- 直接传 raw URL、请求头和未导入接口。
- 未注册容器。
- Bug 查询执行运行写动作。
- 非 Workspace 变更路径和软链接越界。
- 多语句、写 SQL、跨库 SQL 和超限结果。
- 在 Trace、能力事件或可视化中泄漏凭据。

## 29. 验收标准

### 29.1 工具定义质量

- 100% 公共工具和专业动作有非空 description。
- 100% 输入参数有业务语义 description。
- 100% 枚举值在 Schema 和说明中一致。
- 100% next action 引用存在的注册动作。
- 系统文档工具数量与运行时注册表一致。

### 29.2 模型调用质量

以不少于 50 条真实中文任务作为评测集：

- 首个推荐动作 Top 3 命中率不低于 95%。
- 首个实际专业动作正确率不低于 90%。
- 缺少必填参数或非法枚举导致的调用错误率低于 2%。
- 明显命中已发布映射时，不必要 Schema 探索率低于 5%。
- 简单代码修改不出现强制 discover 调用。
- Bug 修复中数据库、接口等辅助调用不改变 primary intent。

### 29.3 功能完整性

- 当前数据、接口、日志、任务可视化结果与改造前一致或更完整。
- 当前数据库、表关联、映射、接口和运行安全策略全部继续生效。
- 同一 task 可以按需跨越至少三个能力包。
- `resolved` 结论只能引用真实成功证据。
- 简单代码开发的 MCP 调用数和整体耗时不显著高于改造前。

## 30. 监控指标

调用链路聚合以下指标：

```text
prepare_recommendation_hit_rate
discover_calls_per_task
invoke_argument_error_rate
capability_expansions_per_task
tool_definition_changed_rate
calls_to_first_success
calls_to_task_resolution
unnecessary_fallback_rate
task_visualization_completion_rate
data_visualization_terminal_rate
interface_execution_success_rate
bug_fix_verification_rate
```

按 Agent、主意图、Workspace 和工具动作筛选，分别比较 Codex、Gemini 和 Antigravity。

指标只使用客观调用元数据，不保存用户凭据、请求头、完整数据库结果或原始日志。

## 31. 发布和回滚

### 31.1 发布前置

- 完成数据库 migration。
- 阶段一至三全部测试通过。
- 五个客户端完成真实 MCP initialize、tools/list、prepare、核心文档链路，以及至少一个专业动作的 discover/invoke 和任务收口。
- 系统文档、接入面板和调用链路支持路由动作展示。

### 31.2 切换方式

- 在一次明确版本发布中切换最终公共工具列表。
- 重启 Context Router 后端。
- 让 Codex、Gemini 和 Antigravity 重新加载 MCP 连接。
- 不同时运行两套公共工具名，避免模型再次看到重复能力。

### 31.3 回滚

回滚只恢复 MCP 公开注册方式，不回滚业务数据：

- `TaskToolRegistry` 和能力事件表可以保留。
- 原专业处理器没有删除，可以重新直接注册。
- 新 task 的 `code_change` 历史继续可读。
- 数据、接口、日志和任务可视化记录不需要转换。

## 32. 文档同步要求

后续实现完成时必须同步：

- `docs/DEVELOPMENT_OUTLINE.md`
- `docs/BUSINESS_FEATURES.md`
- `docs/FRONTEND_BACKEND_FLOW.md`
- `docs/managed/context-router-usage-guide.md`
- `docs/managed/context-router-prepare-guide.md`
- `docs/managed/context-router-trace-guide.md`
- 系统文档中由运行时注册表生成的工具说明

不得继续手写“当前固定有 22/24 个工具”这种容易失真的描述，应改为运行时生成或只描述工具类别。

## 33. 已确认决策

1. 渐进暴露面向所有任务，不为数据库查询单独定制。
2. 代码开发新增独立主意图 `code_change`。
3. Bug 修复和代码开发可以叠加数据库、接口、日志、中间件和表关联能力。
4. 主意图决定最终目标，能力包决定完成目标所需的手段。
5. Agent 原生完成源码搜索、阅读、修改和普通开发测试。
6. Context Router 只在上下文、业务证据、运行编排、验证和任务收口节点介入。
7. 安全边界硬执行，普通工作顺序只推荐不硬拦截。
8. 第一版不依赖动态 `tools/list_changed`。
9. 第一版使用固定公共工具、任务相关动作发现和统一动作调用。
10. `discover_task_tools` 只作兜底，明显场景由 prepare 和前一步结果直接给出动作定义。
11. 现有专业工具业务实现全部复用，不重写领域内核。
12. 支持性数据库查询默认只关联任务证据，不强制创建数据可视化卡片。
13. 实际接口请求和确认的容器错误继续自动进入对应可视化。
14. 最终版本不长期保留重复的直接专业工具入口。

## 34. 后续实现顺序

后续开发严格按以下顺序推进：

1. 建立工具定义注册表和 description/Schema 质量门禁。
2. 增加 `code_change`、能力事件和新版执行契约。
3. prepare 返回 enabled capabilities 和 recommended actions。
4. 实现 `discover_task_tools`。
5. 实现 `invoke_task_tool` 并复用全部现有专业处理器。
6. 改造调用链路保存 transport/resolved tool。
7. 实现 supporting evidence 可视化策略。
8. 完成五客户端和六类真实任务 E2E。
9. 切换最终公共工具列表。
10. 更新业务文档、系统文档和接入面板。

在阶段八验收通过前，不移除现有专业工具的直接注册；在阶段九切换完成后，不长期维护两套重复入口。
