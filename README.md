# Agent Context Router

Agent Context Router 帮助 Codex、Antigravity 等 AI 编程工具更快找到任务所需的项目文档，并把实际阅读链路展示给开发者。

产品层只提供两类入口：

- MCP：AI 自主决定是否获取上下文、读取哪些文档。
- Web：开发者查看 Projects、Documents、Tasks 和每个任务的 MCP 调用链。

后端 HTTP API 仍然保留，但只作为 MCP 和 Web 的内部实现；项目不再提供 `ctx` 或其他 CLI 工作流。

## AI 工作流

1. AI 遇到业务规则、启动、数据库、跨模块链路等依赖稳定文档的任务时，调用 `prepare_task_context`。
2. 传入当前任务 `task`、工作目录 `cwd`，以及可选的 `agent_name`；通常不需要传 project，系统按 cwd 最长路径匹配项目。
3. 系统最多返回 3 份候选文档和 `trace_id`。
4. AI 只对真正需要的候选项调用 `read_context_document(trace_id, document_id)`。
5. 阅读下一层文档时可传 `parent_document_id`，页面会展示父子链路。

如果任务已经明确指出文件、只需搜索源码，或候选文档没有帮助，AI 可以直接使用自己的代码检索能力。系统不要求 AI解释为什么没调用 MCP。

## MCP 工具

### `prepare_task_context`

必填参数：

- `task`：当前任务原文。
- `cwd`：AI 当前工作目录。

可选参数：

- `project`：仅在 cwd 无法识别或需要覆盖时使用。
- `agent_name`：例如 `codex`、`antigravity`。

### `read_context_document`

必填参数：

- `trace_id`：prepare 返回的链路 ID。
- `document_id`：候选文档 ID。

可选参数：

- `parent_document_id`：从上一份文档继续阅读时传入。

## MCP 配置示例

先用 Docker Compose 启动服务，再让 MCP 客户端通过容器执行 stdio server：

```toml
[mcp_servers.context-router]
command = "docker"
args = [
  "compose",
  "-f",
  "/absolute/path/agent-context-router/docker-compose.yml",
  "exec",
  "-T",
  "backend",
  "uv",
  "run",
  "context-router-mcp"
]
```

将示例中的绝对路径替换为本仓库路径。Codex、Antigravity 或其他支持 stdio MCP 的工具都应连接同一个 server。

## 启动与访问

服务统一由本仓库的 Docker Compose 管理：

```bash
docker compose up -d
docker compose exec backend uv run alembic upgrade head
```

- Web：`http://127.0.0.1:49174`
- Internal API：`http://127.0.0.1:49173`
- PostgreSQL：`127.0.0.1:54329`

开发、测试、重启和 migration 规则见 [启动与开发规范](./docs/STARTUP_GUIDE.md)。

## 页面

- Dashboard：项目、活跃文档、MCP 任务、文档阅读数。
- Projects：网页新增项目、同步本地 Markdown、进入项目任务。
- Documents：查看文档清单、关系图和正文。
- Tasks：外层任务列表；点击后查看 prepare 候选、实际 read、父子关系和 MCP 耗时。

页面只展示 `source=mcp` 的任务。数据库保留历史字段和旧表结构用于兼容，但 Usage、反馈和 CLI 已不再作为运行时功能暴露。
