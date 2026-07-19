# 业务功能说明

## 1. 产品目标

本项目只解决两个问题：

1. 让 Codex、Antigravity 等 AI 比全仓库盲搜更快地定位稳定项目文档。
2. 让开发者看到 AI 是否获取了入口、实际读了哪些文档，以及阅读的父子链路。

项目不判断任务是否成功，不要求开发者反馈，也不要求 AI填写不读或停止阅读的原因。

## 2. 项目与文档

- 每个业务项目保存 slug、名称、代码 `root_path`、文档 `docs_path`、描述和可选父项目。
- `root_path` 只负责根据 AI 的 cwd 识别代码项目；`docs_path` 是 `/documents` 下唯一、直接子目录名。
- 每个文档目录只扫描根 `AGENTS.md` 和 `docs/**/*.md`，不扫描代码目录或其他文件夹。
- Projects 页面选择映射、手动同步索引，并展示 reachable、orphan、broken links 和最后同步时间。
- Documents 页面展示按最短可达深度分层的文档图、孤立文档、断链、元数据和实时正文。
- 父项目查询可以包含子项目文档。

多个代码项目都匹配 cwd 时选择 `root_path` 最长、最具体的项目。

## 3. MCP 上下文准备

`prepare_task_context` 接收：

- `task`：必填，当前任务原文。
- `cwd`：必填，当前工作目录。
- `project`：可选，覆盖 cwd 自动识别。
- `agent_name`：可选，调用工具名称。

后端解析项目后只返回该 Project 已同步、active、reachable 的根 `AGENTS.md`，并创建独立 trace。每次调用互不共享状态。

## 4. MCP 文档读取

`read_context_document` 接收：

- `trace_id`：必填，来自 prepare。
- `document_id`：必填，准备读取的文档。
- `parent_document_id`：可选，表示从已读父文档继续向下。

首次 read 只能读取 prepare 返回的入口。后续 read 要求 parent 已在同一 trace 中读取，且目标是 parent 的直接有效 Markdown 链接。后端按实际调用计算 depth 并记录耗时；没有 trace 或越级读取会被拒绝。

## 5. Tasks 可观察链路

Tasks 外层列表只展示 `source=mcp` 的任务：

- 任务文本、项目、AI 工具、时间。
- 返回入口数、实际 read 数、MCP 总耗时。

任务详情展示：

- `prepare_task_context` 请求及返回入口。
- 入口是 `Entry read` 还是 `Entry returned`。
- 每次 `read_context_document` 的 document_id、parent_document_id、实际 depth 和耗时。

页面不展示反馈，不推测“为什么没读”，也不把 Web 管理读取记作 AI 任务。

## 6. AI 何时可以跳过 MCP

以下任务通常可以直接检索代码：

- 用户已经给出明确文件路径。
- 只需找符号、调用点或配置值。
- 内容必须以当前源码为准，稳定说明文档帮助不大。

以下任务更适合先调用 MCP：

- 需要业务边界、数据库信息、启动规范。
- 需要理解多个前后端服务如何流转。
- 新窗口缺少项目背景，且问题表达偏业务而非代码符号。

## 7. 非目标

- 不做任务完成度和成功率评分。
- 不做人工反馈系统。
- 不强制 AI 每次调用 MCP。
- 不把数据库作为项目文档编辑源；数据库只保存索引、图状态和历史链路引用。
- 不提供开发者命令行产品入口。
