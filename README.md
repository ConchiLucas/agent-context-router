# Agent Context Router

Agent Context Router 帮助 Codex、Antigravity 等 AI 编程工具更快找到任务所需的项目文档，并把实际阅读链路展示给开发者。

产品层只提供两类入口：

- MCP：AI 自主决定是否获取上下文、读取哪些文档。
- Web：开发者查看 Projects、Documents、Tasks 和每个任务的 MCP 调用链。

后端 HTTP API 仍然保留，但只作为 MCP 和 Web 的内部实现；项目不再提供 `ctx` 或其他 CLI 工作流。

## AI 工作流

1. AI 遇到业务规则、启动、数据库、跨模块链路等依赖稳定文档的任务时，调用 `prepare_task_context`。
2. 传入当前任务 `task`、工作目录 `cwd`，以及可选的 `agent_name`；通常不需要传 project，系统按 cwd 最长路径匹配项目。
3. 系统只返回该项目映射目录中的 `AGENTS.md` 入口和 `trace_id`。
4. AI 调用 `read_context_document` 阅读入口，再从返回的有效 Markdown 链接选择下一层。
5. 阅读下一层必须传已读的 `parent_document_id`；服务端只允许沿直接链接继续，Tasks 页面展示真实 parent/depth。

如果任务已经明确指出文件、只需搜索源码，或入口文档没有帮助，AI 可以直接使用自己的代码检索能力。系统不要求 AI解释为什么没调用 MCP。

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
- `document_id`：prepare 返回的入口或上一份文档直接链接到的文档 ID。

可选参数：

- `parent_document_id`：从上一份文档继续阅读时传入。

## 文档目录映射

代码项目和文档项目是两个独立定位维度：

```text
AI cwd
  -> Project.root_path 识别代码项目
  -> Project.docs_path 定位 /documents 下的文档目录
  -> AGENTS.md 一级入口
  -> docs/**/*.md 按 Markdown 链接逐层读取
```

服务器上的每个文档项目必须是 `/documents` 的直接子目录，结构固定为：

```text
<docs_path>/
├── AGENTS.md
└── docs/
    ├── business.md
    └── database/schema.md
```

所有被索引的 Markdown 都需要稳定的 front matter `doc_id`。文件正文修改后，下一次 read 会直接读到最新内容；新增、删除、重命名、front matter 或链接变化后，在 Projects 页面点击 **Sync Documents** 更新索引和文档图。

本地默认把仓库的 `document-sources/` 只读挂载为容器 `/documents`。服务器在 `.env` 中设置 `CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT=/srv/ai-docs` 即可映射统一文档目录，不需要修改代码。

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
- Projects：新增项目、选择文档目录映射、同步并查看健康状态。
- Documents：按 AGENTS.md 的可达深度查看文档、孤立文档、断链和实时正文。
- Tasks：外层任务列表；点击后查看 prepare 返回入口、实际 read、真实父子关系和 MCP 耗时。

页面只展示 `source=mcp` 的任务。数据库保留历史字段和旧表结构用于兼容，但 Usage、反馈和 CLI 已不再作为运行时功能暴露。
