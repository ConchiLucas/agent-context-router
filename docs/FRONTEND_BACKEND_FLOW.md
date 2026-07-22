# 前后端链路速查

## 总体链路

```text
Browser
  -> Next.js 项目卡片
  -> FastAPI 项目管理 API
  -> PostgreSQL document_projects
  -> ProjectRegistry 当前运行时缓存
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
| 编辑项目 | `project-dashboard.tsx` | `PUT /api/projects/{id}` |
| 停用/启用项目 | `project-dashboard.tsx` | `PATCH /api/projects/{id}/enabled` |
| 删除项目配置 | `project-dashboard.tsx` | `DELETE /api/projects/{id}` |
| 刷新映射 | `project-dashboard.tsx` | `POST /api/projects/{id}/refresh` |
| 打开全屏树 | `document-tree.tsx` | `GET /api/projects/{id}/tree` |
| 点击节点查看详情 | `markdown-viewer.tsx` | `GET /api/projects/{id}/documents/{document_id}` |
| 查看 MCP JSON | `project-dashboard.tsx` | `POST /api/projects/{id}/prepare-preview` |
| 查看调用记录 | `project-dashboard.tsx`、`task-history.ts` | `GET /api/projects/{id}/tasks`、`GET /api/tasks/{task_id}/document-reads` |
| 打开 MCP 接入面板 | `mcp-integration-panel.tsx` | `GET /api/mcp/integration` |
| 执行 MCP 连接测试 | `mcp-integration-panel.tsx` | `POST /api/mcp/integration/tests` |

## 后端代码

```text
api/projects.py
  -> services/project_registry.py
  -> services/document_tree.py
  -> schemas/projects.py
```

- `ProjectRegistry` 管理多个进程内项目和每个项目的当前缓存。
- `project_repository.py` 持久化稳定项目配置；后端启动时读取所有项目，启用项目从磁盘重建缓存，停用或路径失效项目保留配置但不参与 cwd 匹配。
- 项目新增、编辑、启停和删除先完成必要的磁盘验证与数据库写入，再原子更新注册表；数据库写入失败时不改变当前内存项目。
- `build_document_cache` 负责递归读取、路径校验、循环检测和正文缓存。
- 刷新完成后，`ProjectRegistry` 一次性替换该项目的 `DocumentCache`。
- `document_metadata.py` 在刷新时安全解析显式 title 和 summary。
- `ContextPreparationService` 为 MCP 和卡片 JSON 预览生成同一个返回模型。
- `ContextDocumentReadService` 校验 task/project、批量读取文档或章节，并在返回正文前记录调用。
- `document_read_repository.py` 保存 read_call_id、单次 position、相对路径、章节和状态，不保存正文。
- `mcp_server.py` 注册 `prepare_task_context` 与 `read_context_document`，并挂载到 `/mcp`。
- `mcp_integration.py` 生成客户端配置，并以 MCP Python Client 对后端自身执行 initialize、tools/list、prepare 和 read，不绕过协议直接调用 service。
- 接入测试只返回阶段状态、耗时、task_id、read_call_id 和正文字符数；数据库 URL 与 Markdown 正文不进入 API 响应。

## 前端代码

```text
app/page.tsx
  -> components/project-dashboard.tsx
     -> components/document-tree.tsx
     -> components/markdown-viewer.tsx
     -> components/mcp-integration-panel.tsx
     -> lib/api.ts
     -> lib/markdown.ts
```

Markdown 解析器只生成 React 元素，不使用 `dangerouslySetInnerHTML`，也不执行文档里的原始 HTML。

调用记录通过 `task-history.ts` 同时生成两种序号：按 `read_call_id -> position` 展开的全局文档顺序用于调用列表；按 read call 分组的调用批次号用于完整文档树节点角标。同一批量请求的文档共享批次号，并在调用列表同一行横向展示；同一文档被多次调用时在树节点展示多个批次号。调用记录树节点和读取成功的调用列表卡片均与普通文档树复用 `GET /api/projects/{id}/documents/{document_id}` 和同一个 Markdown 详情抽屉。

MCP 接入信息和测试结果通过 `lib/api.ts` 获取；公开 MCP URL 由后端配置统一提供，前端不按浏览器地址猜测。端到端测试任务的 `agent_name` 固定为 `connection-test`，任务列表默认过滤这类记录。
