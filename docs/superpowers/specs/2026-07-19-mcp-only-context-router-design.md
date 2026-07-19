# Context Router MCP-only 改造设计

日期：2026-07-19

## 1. 目标

将 Agent Context Router 的产品入口统一为 MCP，让 Codex、Antigravity 等 AI Agent 在需要稳定项目上下文时自主检索和阅读文档，并让开发者只通过网页查看任务、候选文档和实际阅读链路。

本次改造删除面向 Agent 和开发者的 `ctx` CLI 协议，但保留 FastAPI HTTP 接口作为 MCP server 和前端的内部实现。

## 2. 已确认原则

- 产品层只保留 MCP，不再维护 CLI 和 MCP 两套 Agent 协议。
- Agent 自主决定是否调用 MCP、是否阅读候选文档。
- 任务列表只展示至少调用过一次 Context Router MCP 的任务。
- V1 不记录未调用、未阅读或停止阅读的原因。
- V1 不收集任务成功率和人工反馈。
- 不要求结束任务、跳过文档或提交反馈等额外 MCP 调用。
- 开发者通过网页查看结果，不执行 Context Router 命令。
- 项目 Markdown 仍保存在各自项目目录；数据库继续作为索引和链路缓存，不成为文档真源。

## 3. 方案边界

### 3.1 删除

- `ctx` CLI 实现和启动脚本。
- Python 包中的 `ctx` console script。
- CLI 会话文件、`SESSION_ID`、`CTX_SESSION_ID`、`CTX_STATE_FILE` 和 `CTX_STATE_DIR`。
- Usage 页面、Usage API、Usage schema、前端类型和内置 ctx 使用卡片。
- Dashboard 的 CLI Entry。
- Documents、Trace 和 Markdown 返回内容中的 `ctx prepare` / `ctx read` 提示。
- 面向用户的反馈控件、反馈 API 和 Dashboard Feedback 指标。
- CLI、Usage 和反馈专属测试。

### 3.2 保留

- FastAPI 项目、文档、prepare、全文读取和 Trace API。
- MCP stdio 启动入口 `context-router-mcp`。
- Projects、Documents 和任务链路数据。
- 本地 Markdown 读取、索引同步和文档链接解析。
- 项目详情页的网页同步入口。
- 既有数据库迁移历史。

### 3.3 暂不清理的历史数据

- `usage_cards` 数据表暂不主动删除，防止自定义卡片数据丢失；运行时代码和页面停止使用它。
- `retrieval_hits.feedback` 字段与历史 feedback events 暂时保留在数据库中，但新 API 和页面不再写入或展示。
- 后端内部继续使用 `Trace` 命名和 `/api/traces` 路径；前端面向用户统一显示为“任务”，避免为文案重命名数据库表。

## 4. 总体架构

```text
项目 AGENTS.md
  -> Agent 判断任务是否可能需要稳定上下文
  -> MCP prepare_task_context
  -> FastAPI /api/context/prepare
  -> 文档索引检索
  -> 返回 trace_id + 最多 3 个候选
  -> Agent 自主决定是否读取
  -> MCP read_context_document
  -> FastAPI /api/documents/{document_id}
  -> 返回本地 Markdown 全文并记录 read event
  -> Tasks 页面展示候选与真实阅读链路
```

MCP server 仍通过内部 HTTP API 调用后端。`CONTEXT_ROUTER_API_URL` 只属于 MCP server 的内部部署配置，不出现在 Agent 工作流说明中。

## 5. MCP 工具契约

### 5.1 `prepare_task_context`

用途：为一个真实任务建立 Trace，并返回少量候选文档。

输入：

```json
{
  "task": "修复登录超时问题",
  "cwd": "/workspace/word-app",
  "project": "word-app",
  "agent_name": "codex"
}
```

字段规则：

- `task` 必填，必须是当前真实任务文本。
- `cwd` 必填，用于识别项目和记录任务位置。
- `project` 可选。没有显式传入时，后端按规范化后的 `cwd` 与 Project `root_path` 做最长前缀匹配。
- `agent_name` 可选，仅用于页面区分 Codex、Antigravity 等调用来源。
- MCP 不暴露 `area`、`max_documents`、entrypoint、route hint 或 output format，避免 Agent 承担路由参数选择。
- 候选上限由服务端固定为 3。

成功返回：

```json
{
  "trace_id": "ctx_01K...",
  "project": "word-app",
  "task": "修复登录超时问题",
  "documents": [
    {
      "document_id": "auth-guide",
      "title": "登录与鉴权说明",
      "score": 18.4,
      "excerpt": "登录态、Token 刷新与超时处理入口...",
      "rank": 1
    }
  ]
}
```

没有匹配文档时仍创建 Trace，并返回空 `documents`；不要求 Agent解释或补充调用。

### 5.2 `read_context_document`

用途：读取一份完整文档，并把读取动作关联到已有任务。

输入：

```json
{
  "trace_id": "ctx_01K...",
  "document_id": "auth-guide",
  "parent_document_id": "project-entry"
}
```

字段规则：

- `trace_id` 必填，禁止使用 MCP 进程全局当前 Trace。
- `document_id` 必填。
- `parent_document_id` 可选；只有从已读文档中的链接继续阅读时传入。
- `depth` 由后端根据同一 Trace 的父文档读取事件计算，Agent 不传。
- 不传 `reason`、`read_mode`、session 或 finish 信息。

成功返回：

```json
{
  "trace_id": "ctx_01K...",
  "document_id": "auth-guide",
  "title": "登录与鉴权说明",
  "source_path": "docs/auth.md",
  "content_markdown": "# 登录与鉴权...",
  "links": [
    {
      "document_id": "auth-debugging",
      "label": "登录故障排查"
    }
  ]
}
```

### 5.3 无状态要求

删除 MCP server 中的：

```text
CURRENT_TRACE_ID
CURRENT_DOCUMENT_ID
CURRENT_DEPTH
```

每个工具调用的归属完全由显式参数确定。两个窗口交错调用时，不得共享或覆盖任务状态。

## 6. 项目识别

项目识别顺序：

1. 如果传入 `project`，按 slug 精确查找并验证存在。
2. 否则规范化 `cwd`，处理宿主机与 Docker workspace 路径映射。
3. 在所有配置了 `root_path` 的项目中选择最长匹配路径。
4. 没有匹配时返回清晰的 MCP 错误，不创建错误归属的 Trace。

父项目与子项目路径都匹配时，优先选择路径更具体的子项目。

## 7. Trace 与客观事件

V1 只记录：

- prepare 任务文本、cwd、项目、Agent、创建时间和服务端处理耗时。
- prepare 返回的文档、rank、score 和 excerpt。
- 每次全文读取的 document id、title、parent document、depth、时间和服务端处理耗时。

V1 不记录：

- Agent 为什么不调用 MCP。
- 候选为什么没有阅读。
- 为什么停止阅读。
- 转向源码检索的原因。
- 任务是否成功。
- 人工 useful/unnecessary/stale/missing 反馈。

“返回但未读”由候选集合减去 read events 自动计算，不需要额外事件。

## 8. 前端信息架构

### 8.1 导航

- `Traces` 改为 `Tasks`。
- 删除 `Usage`。
- Dashboard 删除 CLI Entry 和 Feedback 指标。

### 8.2 任务列表

任务列表只请求或展示 `source=mcp` 的 Trace。

列：

```text
任务 | 项目 | Agent | 候选文档 | 实际阅读 | MCP 耗时 | 时间
```

点击一行进入独立任务详情页，不在列表页并排展示详情。

### 8.3 任务详情

详情页按时间顺序展示：

```text
prepare_task_context
  -> 返回候选 A、B、C
  -> read_context_document A
  -> read_context_document C
```

详情页同时展示候选文档表：

```text
Rank | 文档 | 命中摘要 | Score | 已阅读/未阅读
```

不显示反馈按钮、不读原因、停止原因或成功率。

## 9. CLI 管理能力替代

| 原能力 | MCP-only 后的入口 |
| --- | --- |
| `ctx project add` | Projects 页面新增项目创建和编辑表单 |
| `ctx project init-index` | 项目详情页继续展示可复制的入口模板 |
| `ctx doc add` | 取消单文档命令录入，统一扫描项目 Markdown |
| `ctx doc sync` | 项目详情页的 Reload Links / Sync Documents 按钮 |
| `ctx prepare` | `prepare_task_context` |
| `ctx read` | `read_context_document` |
| `ctx trace` | Tasks 详情页 |
| `ctx reset` | 无状态 MCP 不再需要 |

## 10. 项目接入规则

每个项目的 `AGENTS.md` 只保留短规则：

```markdown
## Context Router

当任务可能需要项目架构、业务规则、开发规范或历史排障信息时，
先调用 `prepare_task_context`。

根据返回的候选自主决定是否调用 `read_context_document`。
不需要文档时可以直接检索源码，无需解释或额外调用。
```

Codex MCP server 配置放在受信任项目的 `.codex/config.toml` 或用户配置中。Antigravity 使用对应的项目 MCP 配置。AGENTS 不包含二进制路径、shell 变量、session 生成或同步命令。

## 11. 错误处理

- `cwd` 无法识别项目：返回项目未注册错误，不生成 Trace。
- 显式 project 不存在：返回 project not found。
- Trace 不存在：read 返回 trace not found，不自动创建 direct-read Trace。
- 文档不存在或本地文件不可读：返回明确错误并保留既有 Trace。
- parent document 不属于同一 Trace 的既有 read event：拒绝 parent 关系，避免生成错误链路。
- prepare 无候选：正常返回空列表。
- 前端接口失败：任务列表显示空态或错误态，不伪造任务数据。

## 12. 兼容与迁移顺序

1. 先实现无状态 MCP 和新测试，确保新入口可用。
2. 改造任务 API 和两级 Tasks 页面。
3. 将项目 AGENTS/MCP 配置迁移到新协议。
4. 删除 CLI、bin/ctx 和所有可见 ctx 提示。
5. 删除 Usage 和反馈运行时功能。
6. 更新 README、业务文档、调用链文档和开发记录。
7. 保留历史数据库字段和 migration，不在本轮破坏已有数据。

迁移过程中不保留面向 Agent 的双写或 fallback。切换完成后，文档和页面只说明 MCP。

## 13. 测试设计

### 后端

- prepare 通过 cwd 自动选择最具体项目。
- 显式 project 覆盖 cwd 推断。
- 无匹配 cwd 不创建 Trace。
- prepare 固定最多返回 3 篇。
- task 为空时拒绝请求。
- read 必须携带有效 trace_id。
- 两个交错 Trace 的 read event 不串联。
- 显式 parent 能产生正确分支和 depth。
- 无效 parent 被拒绝。
- 空候选仍产生可查看的 MCP task。
- 新调用不产生 feedback event。

### 前端

- Tasks 列表只展示 MCP Trace。
- 列表点击进入独立详情页。
- 详情按时间顺序展示 prepare、候选和 read events。
- 候选正确计算已读/未读。
- 页面不出现 ctx、SESSION_ID、Usage 或 Feedback。
- 项目网页同步仍可用。

### 回归

- 文档同步、本地全文读取、项目层级检索和 Markdown 链接解析继续通过。
- Docker Compose 后端 pytest、ruff、format 检查通过。
- Docker Compose 前端 lint 和 build 通过。
- 仓库全局搜索确认运行时代码和当前使用文档不再包含 `ctx prepare`、`ctx read`、`CTX_SESSION_ID` 或 `SESSION_ID` 协议。

## 14. 验收标准

- Codex 和 Antigravity 只看到两个 Context Router MCP 工具。
- 任意两个并发窗口的阅读链路不会串到同一 Trace。
- Agent 无需生成 session id、设置环境变量或执行命令。
- 开发者可以从 Tasks 列表进入独立详情查看候选与实际阅读顺序。
- 未阅读候选能够从客观事件自动显示，但系统不要求原因。
- 项目和文档仍能完全通过网页与后台 API 管理、同步和查看。
- 产品页面、当前 README 和接入文档不再引导用户使用 ctx。

## 15. 本轮不做

- 记录不调用、不阅读或停止阅读原因。
- 任务成功率、人工反馈或离线评测平台。
- 监控未调用 MCP 的 Codex/Antigravity 任务。
- 自动修改所有外部项目文档。
- 删除历史 Usage/Feedback 数据表和字段。
- 将内部 Trace 数据库模型整体重命名为 Task。
- 引入向量检索或 embedding。
