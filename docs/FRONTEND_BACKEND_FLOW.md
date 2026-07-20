# 前后端链路速查

## 总体链路

```text
Browser
  -> Next.js 项目卡片
  -> FastAPI 项目注册表
  -> AGENTS.md 绝对路径映射到容器只读工作区
  -> 递归解析“下级文档”表格
  -> 原子替换内存树和 Markdown 正文索引
```

```text
Codex / Antigravity
  -> POST /mcp
  -> prepare_task_context
  -> ContextPreparationService
  -> ProjectRegistry 按 cwd 定位内存树
  -> PostgreSQL mcp_tasks 生成 task_id
  -> 返回完整文档树 JSON
  -> read_context_document(task_id, requests[])
  -> ContextDocumentReadService 按 project_key 校验任务项目
  -> DocumentCache 按请求顺序返回完整 Markdown 或章节
  -> PostgreSQL 生成 read_call_id 并保存 position/status
```

## 页面到 API

| 页面行为 | 前端 | 后端 API |
| --- | --- | --- |
| 加载项目卡片 | `project-dashboard.tsx` | `GET /api/projects` |
| 添加项目 | `project-dashboard.tsx` | `POST /api/projects` |
| 刷新映射 | `project-dashboard.tsx` | `POST /api/projects/{id}/refresh` |
| 打开全屏树 | `document-tree.tsx` | `GET /api/projects/{id}/tree` |
| 点击节点查看详情 | `markdown-viewer.tsx` | `GET /api/projects/{id}/documents/{document_id}` |
| 查看 MCP JSON | `project-dashboard.tsx` | `POST /api/projects/{id}/prepare-preview` |
| 查看调用记录 | `project-dashboard.tsx` | `GET /api/projects/{id}/tasks`、`GET /api/tasks/{task_id}/document-reads` |

## 后端代码

```text
api/projects.py
  -> services/project_registry.py
  -> services/document_tree.py
  -> schemas/projects.py
```

- `ProjectRegistry` 管理多个进程内项目和每个项目的当前缓存。
- `build_document_cache` 负责递归读取、路径校验、循环检测和正文缓存。
- 刷新完成后，`ProjectRegistry` 一次性替换该项目的 `DocumentCache`。
- `document_metadata.py` 在刷新时安全解析显式 title 和 summary。
- `ContextPreparationService` 为 MCP 和卡片 JSON 预览生成同一个返回模型。
- `ContextDocumentReadService` 校验 task/project、批量读取文档或章节，并在返回正文前记录调用。
- `document_read_repository.py` 保存 read_call_id、单次 position、相对路径、章节和状态，不保存正文。
- `mcp_server.py` 注册 `prepare_task_context` 与 `read_context_document`，并挂载到 `/mcp`。

## 前端代码

```text
app/page.tsx
  -> components/project-dashboard.tsx
     -> components/document-tree.tsx
     -> components/markdown-viewer.tsx
     -> lib/api.ts
     -> lib/markdown.ts
```

Markdown 解析器只生成 React 元素，不使用 `dangerouslySetInnerHTML`，也不执行文档里的原始 HTML。
