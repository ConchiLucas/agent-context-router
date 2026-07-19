# 前后端链路速查

本文件用于从页面或 MCP 工具快速定位到 API、service 和数据库。

## 1. 总体链路

```text
Codex / Antigravity
  -> MCP stdio server
  -> FastAPI internal API
  -> cwd / Project.root_path 识别代码项目
  -> Project.docs_path 定位只读文档目录
  -> AGENTS.md 入口和按链接读取策略
  -> PostgreSQL

Developer browser
  -> Next.js
  -> FastAPI internal API
  -> PostgreSQL
```

## 2. MCP 链路

### prepare_task_context

```text
mcp_server.py:_prepare_task_context
  -> POST /api/context/prepare
  -> api/context.py:prepare_context
  -> services/project_resolution.py:resolve_project
  -> services/document_graph.py:project_entry_document
  -> services/local_document_reader.py 实时读取 AGENTS.md
  -> traces + retrieval_hits + trace_events(prepare)
  -> 唯一 AGENTS.md 入口 + trace_id
```

### read_context_document

```text
mcp_server.py:_read_context_document
  -> GET /api/documents/{document_id}?trace_id=...&source=mcp
  -> api/documents.py:read_document
  -> services/document_graph.py:authorize_mcp_read
  -> 校验 trace project、active/reachable、已读 parent 和直接链接
  -> services/local_document_reader.py 实时读取映射文件
  -> trace_events(read，含 depth 和 duration_ms)
```

## 3. 页面路由

| 页面 | 前端代码 | 后端 API | 用途 |
| --- | --- | --- | --- |
| Dashboard | `frontend/app/page.tsx` | projects/documents/traces GET | 汇总 MCP 任务和文档指标 |
| Projects | `frontend/app/projects/page.tsx` | `GET/POST /api/projects` | 网页新增项目、查看项目卡片 |
| Project detail | `frontend/app/projects/[slug]/page.tsx` | `GET /api/projects/{slug}` | 映射、同步和文档健康状态 |
| Map Documents | `project-document-controls.tsx` | `GET /api/document-mappings/candidates`、`PUT /api/projects/{slug}/document-mapping` | 选择 `/documents` 直接子目录 |
| Sync Documents | `project-link-reload-button.tsx` | `POST /api/projects/{slug}/documents/sync-local` | 扫描映射下的 AGENTS.md、docs/**/*.md 和链接 |
| Documents | `frontend/app/documents/` | `GET /api/documents` | 可达层级、孤立文档、断链和正文 |
| Tasks | `frontend/app/tasks/page.tsx` | `GET /api/traces?source=mcp` | 外层 MCP 任务列表 |
| Task detail | `frontend/app/tasks/[traceId]/page.tsx` | `GET /api/traces/{trace_id}` | prepare/read 调用链详情 |

## 4. 核心后端 API

| API | 文件 | 说明 |
| --- | --- | --- |
| `POST /api/context/prepare` | `api/context.py` | MCP prepare 的内部实现 |
| `GET /api/documents/{id}` | `api/documents.py` | MCP read 或 Web untracked 阅读 |
| `GET /api/traces` | `api/traces.py` | Tasks 列表数据 |
| `GET /api/traces/{id}` | `api/traces.py` | Tasks 详情数据 |
| `GET/POST /api/projects` | `api/projects.py` | 项目列表和创建 |
| `GET /api/document-mappings/candidates` | `api/document_mappings.py` | 可用文档目录及占用状态 |
| `PUT /api/projects/{slug}/document-mapping` | `api/projects.py` | 保存唯一相对 docs_path |
| `POST /api/projects/{slug}/documents/sync-local` | `api/documents.py` | 同步 Markdown 索引 |

不存在 Usage、feedback 或 CLI runtime API。

## 5. 常见排查

### Tasks 没有记录

1. 确认 AI 实际调用了 `prepare_task_context`。
2. 检查 MCP server 使用的 `CONTEXT_ROUTER_API_URL` 或 Docker 容器连接。
3. 检查 `traces.source` 是否为 `mcp`。
4. 查看 `mcp_server.py` 到 `/api/context/prepare` 的错误。

### cwd 无法识别项目

1. 检查 Projects 页中的 root path。
2. 检查 host/container workspace 路径映射。
3. 确认 cwd 位于 root path 下。
4. 多项目匹配时检查最长路径是否是目标项目。

### prepare 没有返回入口

1. 检查 Project 是否已映射且状态不是 invalid。
2. 检查映射根是否有普通文件 `AGENTS.md` 和目录 `docs/`。
3. 点击 Sync Documents，检查入口是否 active、reachable、depth=1。
4. 在 Tasks 详情确认 prepare 是否产生错误或返回入口。

### 文档读取失败

1. 首次读取只能是 prepare 返回的 AGENTS.md；后续 document_id 必须是已读 parent 的直接链接。
2. 检查 trace_id 是否存在。
3. parent_document_id 必须是同一 trace 中更早的 read。
4. 映射文件必须位于 `/documents/<docs_path>` 内，不能是软链接或越界路径。
