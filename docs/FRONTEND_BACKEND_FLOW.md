# 前后端链路速查

本文件用于从页面或 MCP 工具快速定位到 API、service 和数据库。

## 1. 总体链路

```text
Codex / Antigravity
  -> MCP stdio server
  -> FastAPI internal API
  -> retrieval / project resolution / document reader
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
  -> services/retrieval.py:retrieve_documents
  -> traces + retrieval_hits + trace_events(prepare)
  -> 最多 3 个候选文档 + trace_id
```

### read_context_document

```text
mcp_server.py:_read_context_document
  -> GET /api/documents/{document_id}?trace_id=...&source=mcp
  -> api/documents.py:read_document
  -> services/local_document_reader.py
  -> 校验 trace 和 parent_document_id
  -> trace_events(read，含 depth 和 duration_ms)
```

## 3. 页面路由

| 页面 | 前端代码 | 后端 API | 用途 |
| --- | --- | --- | --- |
| Dashboard | `frontend/app/page.tsx` | projects/documents/traces GET | 汇总 MCP 任务和文档指标 |
| Projects | `frontend/app/projects/page.tsx` | `GET/POST /api/projects` | 网页新增项目、查看项目卡片 |
| Project detail | `frontend/app/projects/[slug]/page.tsx` | `GET /api/projects/{slug}` | 项目统计和 MCP 文档模板 |
| Sync Documents | `project-link-reload-button.tsx` | `POST /api/projects/{slug}/documents/sync-local` | 扫描本地 Markdown 和链接 |
| Documents | `frontend/app/documents/` | `GET /api/documents` | 文档清单、关系图、正文 |
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

### 候选不准确

1. 检查文档是否 active、是否已 Sync Documents。
2. 检查 title、document_id、area、tags 是否具体。
3. 查看 `services/retrieval.py` 的打分与父子项目范围。
4. 在 Tasks 详情比较 `Returned only` 与 `Read by AI`。

### 文档读取失败

1. 检查 document_id 是否属于 prepare 返回候选或项目索引。
2. 检查 trace_id 是否存在。
3. parent_document_id 必须是同一 trace 中更早的 read。
4. 本地 Markdown 路径必须位于项目 root path 内。
