# 链路流转速查

本文件只说明前端、后端、CLI、MCP、数据库之间的调用链路和排查入口。业务功能说明见 `docs/BUSINESS_FEATURES.md`。

## 本地服务链路

Docker Compose 端口：

```text
frontend: http://127.0.0.1:49174
backend:  http://127.0.0.1:49173
postgres: 127.0.0.1:54329
```

前端请求后端的配置：

```text
frontend/lib/api.ts
NEXT_PUBLIC_CONTEXT_ROUTER_API_URL
浏览器默认值: http://127.0.0.1:8000
compose 浏览器值: http://127.0.0.1:49173
CONTEXT_ROUTER_INTERNAL_API_URL
compose 服务端渲染值: http://backend:8000
```

后端数据库信息见：

```text
docs/DATABASE_INFO.md
```

启动和重启规则见：

```text
docs/STARTUP_GUIDE.md
```

## 总调用链

浏览器页面：

```text
浏览器页面
  -> frontend/app/*
  -> frontend/lib/api.ts
  -> FastAPI backend/src/context_router/main.py
  -> backend/src/context_router/api/*
  -> backend/src/context_router/services/*
  -> backend/src/context_router/db/models.py
  -> PostgreSQL
```

CLI/MCP：

```text
ctx 命令或 MCP tool
  -> backend/src/context_router/cli.py 或 mcp_server.py
  -> FastAPI HTTP API
  -> backend/src/context_router/api/*
  -> backend/src/context_router/services/*
  -> PostgreSQL
```

## 前端页面到接口

| 页面 | 文件 | 调用接口 | 用途 |
| --- | --- | --- | --- |
| 首页 Dashboard | `frontend/app/page.tsx` | `GET /api/projects`, `GET /api/documents`, `GET /api/traces` | 汇总项目、文档、trace 指标 |
| 项目列表 | `frontend/app/projects/page.tsx` | `GET /api/projects` | 查看顶层项目、聚合 active docs 数量和子项目数量 |
| 项目详情 | `frontend/app/projects/[slug]/page.tsx` | `GET /api/projects/{slug}` | 查看项目详情、子项目和 AI_CONTEXT_INDEX 模板 |
| 文档列表 | `frontend/app/documents/page.tsx` | `GET /api/documents`, `GET /api/projects?include_children=true` | 按 project/area/type/tag/status 筛选文档 |
| 文档详情 | `frontend/app/documents/[documentId]/page.tsx` | `GET /api/documents/{document_id}?untracked=true` | 管理端查看文档元数据和完整正文 |
| Trace 列表 | `frontend/app/traces/page.tsx` | `GET /api/traces` | 查看 prepare 调用历史，可按 project/area/source 筛选 |
| Trace 详情 | `frontend/app/traces/[traceId]/page.tsx` | `GET /api/traces/{trace_id}` | 查看入口元数据、返回文档、读取事件、反馈 |
| Trace 反馈 | `frontend/components/feedback-controls.tsx` | `POST /api/traces/{trace_id}/feedback` | 标记 useful/unnecessary/stale/missing |
| Usage 卡片 | `frontend/app/usage/page.tsx` | `GET/POST/PUT/DELETE /api/usage/cards` | 查看、新增、编辑 Markdown 使用说明卡片 |

前端 API 封装：

```text
frontend/lib/api.ts
frontend/lib/types.ts
```

## 后端入口

FastAPI 应用入口：

```text
backend/src/context_router/main.py
```

注册路由：

```text
/health
/api/projects
/api/context
/api/projects/{project_slug}/documents
/api/documents
/api/traces
/api/usage
```

## 后端接口到代码

| 接口 | 文件 | 作用 |
| --- | --- | --- |
| `GET /health` | `backend/src/context_router/main.py` | 健康检查 |
| `GET /api/projects` | `backend/src/context_router/api/projects.py` | 顶层项目列表，可用 `include_children=true` 返回全部项目 |
| `POST /api/projects` | `backend/src/context_router/api/projects.py` | 创建项目 |
| `GET /api/projects/{project_slug}` | `backend/src/context_router/api/projects.py` | 项目详情、子项目和路由模板 |
| `POST /api/projects/{project_slug}/documents` | `backend/src/context_router/api/documents.py` | 新增或更新上下文文档 |
| `GET /api/documents` | `backend/src/context_router/api/documents.py` | 文档列表和筛选 |
| `GET /api/documents/{document_id}` | `backend/src/context_router/api/documents.py` | 读取文档全文，默认要求 trace/reason，可显式 untracked 调试读取 |
| `POST /api/context/prepare` | `backend/src/context_router/api/context.py` | 根据任务准备上下文文档 |
| `GET /api/traces` | `backend/src/context_router/api/traces.py` | Trace 列表 |
| `GET /api/traces/{trace_id}` | `backend/src/context_router/api/traces.py` | Trace 详情 |
| `POST /api/traces/{trace_id}/feedback` | `backend/src/context_router/api/traces.py` | 记录文档推荐反馈 |
| `GET /api/usage/cards` | `backend/src/context_router/api/usage.py` | Usage 卡片列表，首次访问初始化内置 ctx/SESSION_ID 卡片 |
| `POST /api/usage/cards` | `backend/src/context_router/api/usage.py` | 新增普通 Usage 卡片 |
| `PUT /api/usage/cards/{slug}` | `backend/src/context_router/api/usage.py` | 编辑 Usage 卡片 Markdown 内容 |
| `DELETE /api/usage/cards/{slug}` | `backend/src/context_router/api/usage.py` | 删除非内置 Usage 卡片 |

## 核心流转

### 1. 创建项目

```text
frontend projects 页面或 ctx project add
  -> POST /api/projects
  -> api/projects.py:create_project
  -> db/models.py:Project
```

### 2. 添加上下文文档

```text
ctx doc add
  -> POST /api/projects/{project_slug}/documents
  -> api/documents.py:create_or_update_document
  -> services/document_store.py:upsert_document
  -> documents
```

### 3. 兜底准备任务上下文

```text
ctx prepare 或 MCP prepare_task_context
  -> POST /api/context/prepare
  -> request 可携带 project/area/entrypoint_path/entrypoint_rule/route_hint/source/agent_name
  -> api/context.py:prepare_context
  -> services/retrieval.py:retrieve_documents
  -> services/rendering.py:render_context_markdown
  -> traces + retrieval_hits + trace_events
```

### 4. 读取文档全文

```text
ctx read 或 MCP read_context_document
  -> GET /api/documents/{document_id}?source=...
  -> api/documents.py:read_document
  -> 系统自动使用当前 trace；没有当前 trace 时创建直接读取记录
  -> trace_events 写入 read 事件
```

### 5. 记录推荐反馈

```text
Trace 详情页点击反馈按钮
  -> POST /api/traces/{trace_id}/feedback
  -> api/traces.py:record_feedback
  -> retrieval_hits.feedback
  -> trace_events 写入 feedback 事件
```

### 6. 维护 Usage 卡片

```text
Usage 页面
  -> GET /api/usage/cards
  -> api/usage.py:list_usage_cards
  -> usage_cards
  -> 点击卡片打开 Markdown 弹窗
  -> POST/PUT/DELETE /api/usage/cards
```

## 数据模型关系

```text
Project
  -> children Project
  -> Document
      -> RetrievalHit
  -> Trace
      -> area / entrypoint_path / entrypoint_rule / route_hint / source / agent_name
      -> TraceEvent
      -> RetrievalHit
UsageCard
  -> Markdown 使用说明卡片
```

关键文件：

```text
backend/src/context_router/db/models.py
backend/src/context_router/db/session.py
backend/src/context_router/config.py
```

## 排查入口

### 前端页面打不开

1. 先看 `docs/STARTUP_GUIDE.md`，确认是否应该用 Docker Compose 启动或重启。
2. 检查 `frontend/lib/api.ts` 的后端地址。
3. 检查 `docker-compose.yml` 中 frontend/backend 端口。
4. 检查对应页面文件，例如 `frontend/app/traces/[traceId]/page.tsx`。

### 页面有数据缺失

1. 找页面调用的 `getProjects/getDocuments/getTraces/getTrace`。
2. 找对应后端接口文件。
3. 检查接口 response schema 和 `frontend/lib/types.ts` 是否一致。
4. 查数据库表是否有数据，数据库信息见 `docs/DATABASE_INFO.md`。

### prepare 返回结果不符合预期

优先查看：

```text
backend/src/context_router/api/context.py
backend/src/context_router/services/retrieval.py
backend/src/context_router/services/rendering.py
```

再检查：

```text
documents.status 是否 active
documents.area / tags / doc_type / title 是否命中任务文本
documents.content_markdown 是否包含关键词
retrieval_hits 是否记录了 rank/score/reason
```

### 文档新增后没有被检索到

优先查看：

```text
backend/src/context_router/api/documents.py
backend/src/context_router/services/document_store.py
```

再检查数据库：

```text
documents
```

### trace 或反馈异常

优先查看：

```text
backend/src/context_router/api/traces.py
frontend/app/traces/page.tsx
frontend/app/traces/[traceId]/page.tsx
frontend/components/feedback-controls.tsx
frontend/components/retrieval-hit-list.tsx
frontend/components/trace-timeline.tsx
```

再检查数据库：

```text
traces
trace_events
retrieval_hits
```

## 新功能改动路径

- 新增页面：优先看 `frontend/app/*` 和 `frontend/components/*`。
- 新增后端接口：优先看 `backend/src/context_router/api/*`。
- 新增业务逻辑：优先放在 `backend/src/context_router/services/*`。
- 新增字段：同步修改 SQLAlchemy model、schema、Alembic migration、前端 type。
- 新增数据库结构：必须创建 Alembic migration。
