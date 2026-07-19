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

## 页面到 API

| 页面行为 | 前端 | 后端 API |
| --- | --- | --- |
| 加载项目卡片 | `project-dashboard.tsx` | `GET /api/projects` |
| 添加项目 | `project-dashboard.tsx` | `POST /api/projects` |
| 刷新映射 | `project-dashboard.tsx` | `POST /api/projects/{id}/refresh` |
| 打开全屏树 | `document-tree.tsx` | `GET /api/projects/{id}/tree` |
| 点击节点查看详情 | `markdown-viewer.tsx` | `GET /api/projects/{id}/documents/{document_id}` |

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

