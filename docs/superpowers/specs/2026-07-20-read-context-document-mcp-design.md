# `read_context_document` MCP 技术设计

日期：2026-07-20

## 1. 目标

在现有 Context Router MCP 中新增 `read_context_document` 工具，让 Codex、Antigravity 等 Agent 在调用 `prepare_task_context` 获得完整文档树后，按 `document_id` 一次读取一个或多个 Markdown 文档，并把多次读取稳定地关联到同一个任务。

本设计同时记录每次工具调用及单次调用内的文档顺序，为后续在页面中按“从上到下”的方式展示任务文档读取链路提供数据基础。

## 2. 核心决策

1. `read_context_document` 必须携带 `prepare_task_context` 返回的 `task_id`。
2. 服务端不维护“当前任务”或 MCP 会话状态；Streamable HTTP 继续保持无状态。
3. Codex、Antigravity 不传调用顺序号。每次读取的 `read_call_id` 由 PostgreSQL identity 生成。
4. 单次调用内的文档顺序严格使用请求数组位置 `position`，从 1 开始。
5. 不使用应用锁、任务行锁或“查询最大序号再加一”的计数方式。
6. Markdown 正文仍只保存在内存缓存中，不写入 PostgreSQL。
7. `task_id` 是本地可信环境下的链路关联标识，不作为远程多租户鉴权凭证。

## 3. Agent 调用协议

```text
Codex / Antigravity
  -> prepare_task_context(task, cwd, agent_name?)
  <- task_id + 完整文档树

  -> read_context_document(task_id, requests[])
  <- read_call_id + 按 requests 顺序返回的 Markdown

  -> read_context_document(task_id, requests[])
  <- 下一个 read_call_id + 按 requests 顺序返回的 Markdown
```

MCP server instructions 和工具描述必须明确告诉 Agent：

- 新任务先调用一次 `prepare_task_context`。
- 保存返回的 `task_id`，当前任务后续所有读取都原样传回。
- 新对话或没有 `task_id` 时重新 prepare，不猜测、不复用历史任务号。
- 同一业务任务需要多个 Agent 协作时，由发起方显式把同一个 `task_id` 交给协作者；独立任务分别 prepare。

模型能够在同一对话的工具结果上下文中继续使用结构化 `task_id`。服务端不依赖模型之外的隐式连接状态，因此 MCP 重连或 HTTP 请求变化不会中断链路。

## 4. 工具契约

### 4.1 输入

```json
{
  "task_id": 128,
  "requests": [
    {
      "document_id": "ec88f92002608d3ecb99"
    },
    {
      "document_id": "1cf93a8b717ce0404b97",
      "section": "本地启动关系"
    }
  ]
}
```

字段定义：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `task_id` | 是 | 正整数，必须对应已经成功创建的 `mcp_tasks.id` |
| `requests` | 是 | 1 到 10 项，响应顺序与数组顺序完全一致 |
| `requests[].document_id` | 是 | 必须是 prepare 文档树返回的文档 ID |
| `requests[].section` | 否 | Markdown ATX 标题文本，不包含 `#`；未传时返回完整文档 |

允许同一文档在一次调用中出现多次，以读取不同章节。完全相同的重复项也保持原顺序返回，不在服务端重排或去重。

### 4.2 成功返回

```json
{
  "task_id": 128,
  "read_call_id": 301,
  "documents": [
    {
      "position": 1,
      "document_id": "ec88f92002608d3ecb99",
      "path": "docs/call-chain.md",
      "title": "调用链排查地图: panzhihua-dsly-workforce",
      "content": "---\ntitle: ...\n---\n..."
    },
    {
      "position": 2,
      "document_id": "1cf93a8b717ce0404b97",
      "path": "docs/database-connections.md",
      "title": "数据库连接信息: panzhihua-dsly-workforce",
      "section": "本地启动关系",
      "content": "## 本地启动关系\n..."
    }
  ]
}
```

返回约束：

- `documents` 与 `requests` 一一对应，不按树位置、标题或相关度排序。
- 返回项目相对路径，不返回宿主机路径或容器路径。
- 返回缓存中的 Markdown 原文，不生成摘要、不改写正文、不调用大模型。
- 完整文档读取保留原始 Front Matter；章节读取只返回目标标题及其章节内容。
- 不返回同一文档的 summary、children 等 prepare 已经提供且本次读取不需要的字段。
- 不静默截断正文。超过响应安全上限时返回明确错误，提示改为按章节读取。

## 5. 章节读取规则

`section` 使用可预测的 Markdown ATX 标题规则：

1. 支持 `#` 到 `######` 标题。
2. 输入值去除首尾空白后，与标题文本精确匹配，不做模糊搜索。
3. 返回内容从命中的标题行开始，到下一个同级或更高级标题之前结束。
4. 没有匹配标题时返回该请求项的 `section_not_found` 错误。
5. 同一文档出现多个同名标题时返回 `section_ambiguous`，不擅自选择第一个。
6. 不解析代码块内部看起来像标题的文本。

章节解析作为纯函数实现并单独测试，不修改缓存中的原始正文。

## 6. 任务隔离与项目校验

一次读取按以下顺序校验：

1. 根据 `task_id` 查询 `mcp_tasks`。
2. 取得任务保存的稳定 `project_key`，不使用会在后端重启后变化的运行时 `project_id`。
3. 通过 `project_key` 在 `ProjectRegistry` 中找到当前项目快照。
4. 每个 `document_id` 只能从该项目快照的 `DocumentCache.documents` 中解析。
5. 文档不属于任务项目时统一返回 `document_not_found`，不能跨项目读取，也不向调用方透露该 ID 是否存在于其他项目。

这样即使同时存在多个 Codex 或 Antigravity 任务，每条读取记录也只会进入其显式 `task_id` 对应的链路。

需要明确：本地版本中的自增 `task_id` 负责关联和防止意外串线，但不是安全令牌。若 MCP 未来开放给远程、多用户环境，需要增加认证主体和不可猜测的 task token；本轮继续保持仅监听 `127.0.0.1` 的本地安全边界。

## 7. 文档刷新一致性

`read_context_document` 读取 `ProjectRegistry` 当前缓存快照：

- 获取快照后立即释放 Registry 锁。
- 当前读取始终使用同一个不可变 `DocumentCache` 引用。
- 与刷新并发时，要么读取刷新前完整缓存，要么读取刷新后完整缓存，不会读到半次刷新结果。
- 如果 prepare 后文档被刷新并删除，读取对应 ID 返回 `document_not_found`，提示 Agent 重新调用 prepare。
- 本轮不为每个任务持久化整棵文档快照，避免在数据库重复保存树和正文。

## 8. 数据库设计

新增 migration `20260720_0002_create_mcp_document_reads.py`。

### 8.1 读取调用表

```sql
CREATE TABLE mcp_document_read_calls (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES mcp_tasks(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_mcp_document_read_calls_task_id_id
    ON mcp_document_read_calls(task_id, id);
```

`id` 就是返回的 `read_call_id`。同一任务的多次调用使用 `ORDER BY id` 展示。PostgreSQL sequence 可能因事务回滚出现空洞，这是正常现象，不影响顺序。

### 8.2 单次调用文档表

```sql
CREATE TABLE mcp_document_read_items (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    read_call_id BIGINT NOT NULL
        REFERENCES mcp_document_read_calls(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL,
    document_id VARCHAR(20) NOT NULL,
    document_path TEXT,
    requested_section TEXT,
    status VARCHAR(32) NOT NULL,
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mcp_document_read_items_call_position
        UNIQUE (read_call_id, position)
);

CREATE INDEX ix_mcp_document_read_items_call_position
    ON mcp_document_read_items(read_call_id, position);
```

数据库只保存：

- 调用归属。
- 输入顺序。
- 文档 ID 和项目相对路径快照。
- 请求章节、成功或失败状态、错误码。

数据库不保存 Markdown 正文，避免敏感文档内容重复落库，也避免任务记录表快速膨胀。

## 9. 调用顺序保证

一次任务的展示顺序为：

```sql
ORDER BY mcp_document_read_calls.id,
         mcp_document_read_items.position
```

示例：

```text
任务 128
├── 调用 301
│   ├── 位置 1：call-chain.md
│   └── 位置 2：database-connections.md / 本地启动关系
└── 调用 307
    └── 位置 1：environment-logins.md
```

不要求 Agent 传 sequence，也不执行以下危险模式：

```sql
SELECT MAX(sequence) + 1 ...
```

因此不存在同一任务并发调用时的序号竞争，不需要锁。若两个请求真正并发，`read_call_id` 表示 PostgreSQL 为调用分配记录号的先后；这就是页面采用的稳定展示顺序。

## 10. 事务与失败策略

服务端流程：

1. 校验 `task_id` 和请求数组。
2. 查询任务并定位项目快照。
3. 按输入顺序解析文档和可选章节。
4. 单个数据库事务写入一条 read call 和全部 read items。
5. 事务提交成功后返回正文。

任务不存在、项目不可用或数据库写入失败时，整个 MCP 调用返回工具错误，不返回未记录的正文。

单个文档或章节无效时采用逐项错误，其余合法文档仍正常返回：

```json
{
  "position": 2,
  "document_id": "bad-id",
  "error": {
    "code": "document_not_found",
    "message": "文档不在当前任务项目的映射中"
  }
}
```

失败项同样写入 `mcp_document_read_items`，便于页面完整展示 Agent 实际尝试过的读取顺序。错误信息不包含绝对路径、数据库连接串或 Python 堆栈。

## 11. 服务端模块划分

```text
backend/src/context_router/
├── mcp_server.py
│   # 注册 read_context_document；更新两步调用说明
├── schemas/context.py
│   # ReadDocumentRequest、ReadContextDocumentResult 等模型
├── services/
│   ├── context_document_read.py
│   │   # 任务解析、项目隔离、批量读取、章节提取、返回组装
│   ├── markdown_section.py
│   │   # 纯函数章节解析
│   └── project_registry.py
│       # 增加按稳定 project_key 取得快照
├── repositories/
│   ├── task_repository.py
│   │   # 增加按 task_id 查询任务
│   └── document_read_repository.py
│       # read call/items 事务写入和历史查询
└── migrations/versions/
    └── 20260720_0002_create_mcp_document_reads.py
```

`mcp_server.py` 继续只做参数接收、调用 service 和把领域错误转换为 `ToolError`，不承载读取和数据库逻辑。

## 12. 页面调用链展示

为实现此前确认的“从上到下列出来”效果，后续页面读取以下数据：

- `GET /api/projects/{project_id}/tasks`：列出该项目最近任务。
- `GET /api/tasks/{task_id}/document-reads`：返回按 `read_call_id`、`position` 排好的读取历史。

页面布局保持简单：

```text
任务标题 / Agent / task_id

[第 1 次调用]
  1. call-chain.md
  2. database-connections.md / 本地启动关系

[第 2 次调用]
  1. environment-logins.md
```

文档卡片只做纵向排列，不绘制文档之间的连线，不暗示依赖或因果关系。调用分组用于区分“一次批量读取”和“下一次工具调用”。

本轮可以先完成 MCP、数据库记录和历史查询 API；页面可在数据结构确认后作为独立 UI 步骤实现，避免 MCP 核心能力被界面细节阻塞。

## 13. 限制与防止 Token 浪费

- 单次最多 10 个读取项。
- 单篇完整文档超过 200,000 字符时返回 `document_too_large`，要求使用 `section`。
- 单次成功正文合计超过 400,000 字符时返回 `response_too_large`，不静默截断。
- 无 summary 的文档仍然可以按 ID 读取；服务端不生成兜底摘要。
- 不做检索、相关度判断、自动扩展子文档或“顺便读取”链接文档。

这些限制只防止误调用造成超大工具结果，不改变文档选择权；Agent 仍然根据 prepare 返回的完整树自行决定读取内容。

## 14. 测试方案

### 14.1 Service

- 一个 task 读取一个完整文档。
- 一个 task 一次读取多个文档，响应顺序与请求一致。
- 同一文档读取多个章节时保持输入顺序。
- 章节范围正确，忽略代码块中的伪标题。
- 标题不存在或同名标题重复时返回明确逐项错误。
- task 不存在时不读取、不落 read call。
- 文档属于其他项目时拒绝读取。
- prepare 后项目刷新时只使用完整旧缓存或完整新缓存。
- 数据库写入失败时不返回 Markdown 正文。

### 14.2 Repository / migration

- `mcp_document_read_calls.task_id` 外键有效。
- 删除任务时读取记录级联删除。
- 单次调用的 `position` 唯一。
- 多个并发调用得到不同的 `read_call_id`，不需要应用锁。
- 数据库中不出现 Markdown 正文。

### 14.3 MCP transport

- `tools/list` 按名称暴露 `prepare_task_context` 和 `read_context_document`。
- 标准链路 `prepare -> read(task_id)` 成功。
- 缺少 `task_id` 由 MCP 参数校验拒绝。
- 无效 task、跨项目 document 和章节错误返回稳定错误结构。
- MCP 断开并重新连接后，携带原 task_id 仍可继续读取。

### 14.4 页面历史

- 调用按 `read_call_id` 从小到大展示。
- 单次调用内按 `position` 展示。
- 成功和失败读取都有明确状态。
- 不绘制文档关系连线。

所有迁移、测试、lint 和 build 按 `docs/STARTUP_GUIDE.md` 使用 Docker Compose 执行。

## 15. 验收标准

1. Agent 必须使用 prepare 返回的 `task_id` 调用读取工具。
2. 一次调用可读取 1 到 10 个完整文档或指定章节。
3. 返回顺序严格等于请求数组顺序。
4. 文档只能来自 task 绑定项目，不能跨项目读取。
5. 多次调用使用 PostgreSQL 生成的 `read_call_id` 稳定排序，不需要 Agent sequence 或服务端锁。
6. 每个读取项以 `position` 保存，页面能按调用、按项从上到下展示。
7. PostgreSQL 不保存 Markdown 正文。
8. MCP 保持 stateless HTTP，重连后凭 task_id 继续同一链路。
9. 错误不会泄露绝对路径、数据库凭证或堆栈。
10. 原有 prepare、项目页面和文档树功能不受影响。

## 16. 建议实施顺序

1. Migration 与 repository：先建立 task 查询、read call/items 持久化。
2. Registry 与读取 service：完成 project_key 定位、批量读取、章节解析。
3. MCP 工具：注册 `read_context_document` 并更新 server instructions。
4. 测试与标准 MCP 联调：实际执行 `prepare -> read -> read`，核对数据库顺序。
5. 历史查询 API。
6. 纵向任务读取链路页面。
