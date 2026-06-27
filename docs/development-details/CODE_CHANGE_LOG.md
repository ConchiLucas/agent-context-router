# 代码变更记录

本文件用于记录跨模块、数据结构、接口 contract、工程约定等重要代码变更。

## 记录规则

- 按日期追加记录。
- 只记录代码层面的开发信息，不记录普通聊天。
- 简要结论可同步到 `../DEVELOPMENT_OUTLINE.md`。
- 如果内容影响启动、数据库、业务功能或链路流转，需要同步更新对应文档。

## 记录

### 2026-06-27

- 建立 `docs/DEVELOPMENT_OUTLINE.md` 作为代码开发大纲。
- 新建 `docs/development-details/` 目录，用于按类型存放开发细节。
- 根目录 `AGENTS.md` 保留一级索引，开发细节通过大纲按需读取。
- 移除文档切分功能：后端删除 `DocumentChunk`、`document_chunks`、`chunk_id/chunk_count` 和 `chunking.py`；检索改为直接使用 `documents.content_markdown`；前端移除 Chunks 展示；新增 migration `20260627_0003_remove_document_chunks`。
- 补齐任务入口路由：`ctx prepare`、MCP 和 `/api/context/prepare` 支持 `area`、入口路径、入口规则、route hint、source、agent_name；trace 增加对应字段；检索支持按 area 收窄；前端 trace 展示入口元数据和 returned-but-unread；新增 migration `20260627_0004_add_trace_routing_metadata`。
- 收紧受管文档读取：`GET /api/documents/{document_id}` 默认要求 trace/reason 并校验 trace 存在；CLI/MCP 读取会记录 source；显式 `untracked=true` 仅用于管理或调试读取。
- 新增 `ctx project init-index`，用于按 project 和 area 生成短 `AI_CONTEXT_INDEX.md` 入口索引。
- 修正前端 Docker 环境下的后端访问地址：服务端渲染使用 `CONTEXT_ROUTER_INTERNAL_API_URL=http://backend:8000`，浏览器端继续使用 `NEXT_PUBLIC_CONTEXT_ROUTER_API_URL=http://127.0.0.1:49173`。
- 新增文档详情页：Documents 列表文档标题可点击进入 `/documents/{documentId}`，管理端通过 `untracked=true` 查看文档元数据和完整 `content_markdown`。
- 新增项目父子层级：`projects.parent_project_id` 支持大项目聚合子项目；`GET /api/projects` 默认返回顶层项目，`include_children=true` 返回全部项目；项目详情返回 `children`；前端 Projects 页展示大项目，详情页展示子项目列表；新增 migration `20260627_0005_add_project_hierarchy`。
- 重做 Projects 页面卡片：项目卡片内展示聚合 Documents 和 Traces 信息，并提供跳转到相关 Documents/Traces 的两个按钮；`GET /api/projects` 增加 `trace_count`；`GET /api/documents` 和 `GET /api/traces` 的 `project` 筛选支持父项目包含子项目。
- 调整 Projects 卡片布局：桌面端项目卡片使用两列网格，一行可展示两个 Project 卡片，窄屏自动回到单列。
- 收敛受管文档入库边界：清理过细的配置、表结构、manifest、重复清单等文档，将工作区托管文档重置为每个项目的 `AGENTS.md` 和 `AI_CONTEXT_INDEX.md`；后续配置/表结构/源码细节由 AI 按需直接读取项目目录。
- 调整 Projects 卡片按钮交互：Documents/Traces 不再跳转到侧边栏菜单页，而是在 `/projects?panel=...` 中打开覆盖右侧主区域的全页弹窗；弹窗复用 Documents/Traces 页面视图，并提供 Back 返回 Projects。
- 调整 Documents 弹窗内的文档详情交互：从 Projects 的 Documents 弹窗点击文档时，在右侧主区域继续打开嵌套详情弹窗，并支持 Back 返回当前 Documents 列表。
- 优化文档详情弹窗顶部布局：标题、Metadata 和 Read Command 改为紧凑摘要区，减少上方区域高度，让正文内容更早展示。
- 修复文档详情弹窗标题被 Back 工具条遮挡的问题：嵌套详情层工具条改为普通占位布局，不再 sticky 覆盖内容。
