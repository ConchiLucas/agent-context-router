# `prepare_task_context` MCP 技术设计

日期：2026-07-20

## 1. 目标

在现有 Context Router 后端中新增一个标准 MCP 工具 `prepare_task_context`。Codex、Antigravity 等 Agent 在任务开始时调用一次，服务端根据 `cwd` 定位已经注册的项目，创建任务号，并返回该项目的完整文档树。

文档树中的 `title` 和 `summary` 只读取 Markdown 文件开头的 YAML Front Matter；不从正文、标题或文件名推导概要。

## 2. 本轮范围

本轮只实现：

- Streamable HTTP MCP 入口。
- `prepare_task_context` 一个工具。
- 根据 `cwd` 定位项目。
- 读取显式 `title` / `summary` 元数据。
- 返回当前项目的完整文档树。
- 在本地 PostgreSQL 中创建任务记录并返回任务号。

本轮不实现：

- `read_context_document`。
- 文档搜索、打分、排序、Top N 或正文摘要生成。
- 任务调用历史页面和文档读取时间线。
- 文档正文返回。
- Markdown 写回磁盘。
- 自动监听文件变化。

## 3. 现状与最小改造路径

当前后端已经具备：

- `ProjectRegistry`：维护已注册项目及其当前内存缓存。
- `DocumentCache`：保存完整树和 Markdown 原文。
- `build_document_cache`：按照 `## 下级文档` 表格递归构建树。
- Docker 工作区只读挂载和宿主机/容器路径映射。

因此不重新扫描目录，也不为 MCP 建立第二套文档索引。`prepare_task_context` 直接读取 `ProjectRegistry` 中已经完成原子刷新的 `DocumentCache`，确保网页和 MCP 看到的是同一个版本。

## 4. 总体架构

```text
Codex / Antigravity
  -> Streamable HTTP /mcp
  -> prepare_task_context(task, cwd, agent_name?)
  -> ContextPreparationService
       -> ProjectRegistry：按 cwd 最长前缀定位项目
       -> DocumentCache：取得完整内存树
       -> TaskRepository：PostgreSQL 创建任务号
       -> 将树转换为 MCP 精简结构
  -> 返回 task_id + project + documents
```

MCP ASGI 应用挂载到现有 FastAPI 进程，不通过 HTTP 再调用本机 FastAPI API。这样可直接复用同一份 `ProjectRegistry` 和文档缓存，避免内部转发、重复序列化以及两份状态不一致。

## 5. MCP 传输与接入

### 5.1 传输

使用 Python MCP SDK 的 FastMCP 与 Streamable HTTP：

- URL：`http://127.0.0.1:49173/mcp`
- HTTP 模式保持无状态；任务状态以显式 `task_id` 为准。
- MCP server 与 FastAPI 共用 lifespan，启动和关闭 MCP session manager。
- 返回 JSON structured content，不返回额外的人类说明文本。

Codex 和 Antigravity 都连接同一个 HTTP URL，不额外维护 stdio 包装脚本。

### 5.2 本地安全边界

MCP 仅供本机 Agent 使用：

- Docker Compose 的后端端口改为绑定 `127.0.0.1:49173:8000`。
- MCP 不接受任意文档目录或 AGENTS.md 路径。
- MCP 只能访问已经注册且已经缓存的项目。
- 返回项目相对路径，不返回容器路径或宿主机绝对文档路径。
- 本轮不开放文档正文，因此不会通过 prepare 返回数据库口令等正文内容。

如果未来需要远程访问，再单独设计 HTTPS、鉴权和访问审计；本轮不扩大边界。

## 6. 工具契约

### 6.1 输入

```json
{
  "task": "修复多式联运后台登录后的菜单权限问题",
  "cwd": "/Users/conchi/workforce/company_workforce/panzhihua_workforce/panzhihua_dsly_workforce/c12-mtp-ui",
  "agent_name": "codex"
}
```

字段：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `task` | 是 | 去除首尾空白后非空，最大 4000 字符；保存任务原文，不参与文档排名 |
| `cwd` | 是 | 必须是绝对路径，用于项目定位，不允许客户端直接传项目 ID |
| `agent_name` | 否 | 最大 64 字符，例如 `codex`、`antigravity`；未传时不推断 |

工具不提供 `query`、`limit`、`max_documents`、`area`、`rank` 或 `score` 参数。

### 6.2 成功返回

```json
{
  "task_id": 128,
  "project": {
    "project_id": "9e3c...",
    "name": "攀枝花多式联运",
    "node_count": 15
  },
  "documents": {
    "document_id": "a82f...",
    "path": "AGENTS.md",
    "title": "AI 入口索引: panzhihua-dsly-workforce",
    "summary": "攀枝花多式联运聚合工作区的 AI 导航入口……",
    "children": [
      {
        "document_id": "9b31...",
        "path": "docs/call-chain.md",
        "title": "调用链排查地图: panzhihua-dsly-workforce",
        "summary": "梳理前端、Nginx、后端模块、Feign、MQ 和 TaskCenter 的本地调用路径……",
        "children": []
      }
    ]
  }
}
```

返回约束：

- `documents` 是一棵完整树，不排名、不截断。
- 子节点顺序严格保持 Markdown `下级文档` 表格中的声明顺序。
- `title`、`summary` 没有配置时直接省略字段，不返回 `null`、空字符串或“暂无概要”。
- 不返回 Markdown 正文、候选分数、摘录、绝对路径和重复的平铺文档数组。
- `document_id` 由服务端生成，Agent 只需原样保存并在未来读取工具中传回。
- 错误节点仅增加 `error` 字段；正常节点不返回 `error: null`。

## 7. Front Matter 解析规则

支持以下格式：

```markdown
---
title: 启动与开发规范
summary: 说明项目前后端启动、重启、测试、构建及数据库迁移的统一操作方式。
---
```

规则：

1. Front Matter 必须从文件第一行开始。
2. 起止分隔符都必须是独立的 `---` 行。
3. 使用安全 YAML 解析，不构造任意 Python 对象。
4. 只消费非空字符串类型的 `title` 和 `summary`。
5. 没有 Front Matter 或没有 `summary` 都是合法情况。
6. 不读取第一段、Markdown 标题、表格说明或文件名来生成 `summary`。
7. Front Matter 存在但 YAML 非法时，将该节点标记为元数据错误，不使用正文兜底。

`CachedDocument` 与 `CachedTreeNode` 增加可选 `title`、`summary` 字段。元数据在刷新项目时解析一次并缓存，prepare 调用时不重复读取磁盘。

## 8. 项目定位

项目根目录定义为已注册 `agents_path` 的父目录。

定位流程：

1. 校验 `cwd` 是绝对路径并进行词法规范化。
2. 根据现有 `workspace_host_root` / `workspace_container_root` 配置统一宿主机和容器路径。
3. 查找所有满足“项目根目录是 cwd 的父路径”的已注册项目。
4. 多个项目都匹配时选择根目录最长、最具体的项目。
5. 没有匹配时返回 MCP tool error，不创建任务记录，也不默认归到第一个项目。

项目定位只基于已注册项目，不检查客户端传入路径下的文件，也不动态添加项目。

## 9. 任务号与 PostgreSQL

本轮只建立一张任务表：

```sql
CREATE TABLE mcp_tasks (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    project_key VARCHAR(64) NOT NULL,
    project_name VARCHAR(120) NOT NULL,
    task TEXT NOT NULL,
    cwd TEXT NOT NULL,
    agent_name VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

设计说明：

- `id` 就是返回给 Agent 的 `task_id`。
- 使用 PostgreSQL identity 自动生成，不由 Codex 或 Antigravity传入。
- 不维护“每任务下一个序号”，不使用应用层锁或任务行锁。
- 当前项目注册表是进程内数据，运行时 `project_id` 重启后会变化，因此任务表保存稳定的 `project_key` 和项目名称快照，不建立到运行时项目 ID 的外键。
- `project_key` 由规范化后的宿主机 AGENTS.md 路径生成稳定哈希。
- 后续实现读取工具时，再增加独立的读取调用表并用 `task_id` 关联；不在本轮提前创建。

数据库连接通过 `CONTEXT_ROUTER_DATABASE_URL` 注入。Docker 内连接宿主机 PostgreSQL 时使用 `host.docker.internal`，仓库不保存账号口令。

数据库迁移使用正式 migration，不在应用启动时执行 `CREATE TABLE IF NOT EXISTS`。数据库不可用或插入失败时，prepare 返回明确工具错误，不生成没有任务号的半成功响应；现有 Projects 页面仍可正常使用。

## 10. 服务端模块划分

计划新增或调整：

```text
backend/src/context_router/
├── mcp_server.py                 # FastMCP 定义，只注册 prepare_task_context
├── services/
│   ├── context_preparation.py    # 输入校验、项目定位、任务创建、树转换
│   ├── document_metadata.py      # Front Matter 安全解析
│   ├── project_registry.py       # 增加按 cwd 定位和读取缓存快照
│   └── document_tree.py          # 缓存 title / summary / 项目相对路径
├── repositories/
│   └── task_repository.py        # INSERT mcp_tasks ... RETURNING id
├── schemas/
│   └── context.py                # MCP 输入输出 Pydantic 模型
└── main.py                       # 挂载 /mcp 并组合 lifespan
```

MCP tool 函数保持薄层，只调用 `ContextPreparationService.prepare()`。业务逻辑不写在工具装饰器中，便于不启动 MCP transport 的单元测试。

## 11. 执行顺序与一致性

一次 prepare 的服务端顺序：

1. 校验输入。
2. 根据 `cwd` 定位项目。
3. 在 `ProjectRegistry` 锁内取得不可变的缓存引用和项目摘要，然后立即释放锁。
4. 向 PostgreSQL 插入任务并取得 `task_id`。
5. 将刚才取得的缓存快照转换为精简 MCP 树并返回。

项目刷新继续采用“新缓存完整构建后原子替换”。prepare 要么读取刷新前的完整树，要么读取刷新后的完整树，不会读到半棵树。数据库 identity 的并发安全由 PostgreSQL 保证，不增加序号锁。

## 12. 错误模型

| 情况 | 结果 |
| --- | --- |
| `task` 为空或超长 | MCP 参数错误 |
| `cwd` 不是绝对路径 | MCP 参数错误 |
| cwd 没有匹配已注册项目 | `project_not_found` 工具错误，不写任务表 |
| 项目尚无有效缓存 | `project_not_ready` 工具错误，不写任务表 |
| PostgreSQL 不可用 | `task_store_unavailable` 工具错误 |
| Front Matter 缺少 summary | 正常返回节点，省略 summary |
| Front Matter YAML 非法 | 节点带精简 error，不做正文兜底 |
| 文档树包含缺失文件节点 | 保留当前树错误节点，不中断其他节点返回 |

错误内容不返回 Python 堆栈、数据库连接串或宿主机敏感路径。

## 13. 测试方案

### 13.1 文档元数据

- 能读取合法 `title` 和 `summary`。
- 没有 Front Matter 时两个字段均为空。
- 只有 title 时不生成 summary。
- 不从 H1 或第一段兜底生成 summary。
- 非法 YAML 产生节点元数据错误。
- Markdown 正文中的第二个 `---` 块不被当成 Front Matter。

### 13.2 项目定位

- cwd 位于项目根目录时正确匹配。
- cwd 位于任意深度子目录时正确匹配。
- 父子项目同时匹配时选择更具体的项目。
- 宿主机路径和 `/workspace` 容器路径映射结果一致。
- 无匹配 cwd 不创建任务。

### 13.3 prepare 服务

- 返回完整递归树并保持声明顺序。
- 返回的节点数与 ProjectRegistry 当前缓存一致。
- 没有 summary 的节点不包含 summary 键。
- 不返回正文、绝对路径、rank、score 或 excerpt。
- 每次成功调用获得不同的 PostgreSQL 自增 task_id。
- 两个并发调用不需要应用锁，task_id 唯一。
- 数据库插入失败时不返回半成功结果。
- 项目刷新与 prepare 并发时只返回完整旧树或完整新树。

### 13.4 MCP transport

- MCP initialize 成功。
- tools/list 只包含 `prepare_task_context`。
- tools/call 返回结构化 JSON。
- 非法参数以 MCP tool error 返回，服务连接保持可用。
- `/health` 和现有 `/api/projects` 行为不受影响。

所有测试、lint、migration 和启动验证继续通过当前项目 Docker Compose 执行。

## 14. 验收标准

1. Codex 与 Antigravity 都能通过 `http://127.0.0.1:49173/mcp` 发现且调用唯一工具 `prepare_task_context`。
2. 传入攀枝花任一子项目 cwd 时，返回服务端生成的 `task_id` 和完整 15 节点文档树。
3. 已人工填写 summary 的 13 个节点返回 summary，另外两个节点不出现 summary 字段。
4. 返回体不包含任意 Markdown 正文和宿主机/容器绝对文档路径。
5. 重复调用不做检索或摘要生成，每次只创建任务并序列化当前缓存。
6. PostgreSQL 自动生成任务号；客户端不传序号，服务端不实现每任务计数器或锁。
7. 本轮代码库中不存在 `read_context_document` 的工具实现。

## 15. 后续但不属于本轮

下一步若用户确认，再单独设计和实现 `read_context_document`：支持一次传多个 `document_id`，按输入顺序读取，并以 `task_id` 关联调用记录。该能力不应反向扩大本轮 prepare 的返回内容或参数。
