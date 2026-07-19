# 业务功能说明

## 1. 产品目标

本项目只解决两个问题：

1. 让 Codex、Antigravity 等 AI 比全仓库盲搜更快地定位稳定项目文档。
2. 让开发者看到 AI 获取了哪些候选文档、实际读了哪些文档，以及阅读的父子链路。

项目不判断任务是否成功，不要求开发者反馈，也不要求 AI填写不读或停止阅读的原因。

## 2. 项目与文档

- 每个业务项目保存 slug、名称、root path、描述和可选父项目。
- 文档源仍在各自项目仓库，Context Router 数据库只保存索引、内容缓存和关系。
- Projects 页面可以新增项目并同步 root path 下的 Markdown。
- Documents 页面展示文档清单、关系图、元数据和正文。
- 父项目查询可以包含子项目文档。

root path 同时用于 MCP 的 cwd 自动识别。多个项目都匹配时选择路径最长、最具体的项目。

## 3. MCP 上下文准备

`prepare_task_context` 接收：

- `task`：必填，当前任务原文。
- `cwd`：必填，当前工作目录。
- `project`：可选，覆盖 cwd 自动识别。
- `agent_name`：可选，调用工具名称。

后端检索项目及子项目中的 active 文档，最多返回 3 份候选文档，并创建独立 trace。每次调用互不共享状态。

## 4. MCP 文档读取

`read_context_document` 接收：

- `trace_id`：必填，来自 prepare。
- `document_id`：必填，准备读取的文档。
- `parent_document_id`：可选，表示从已读父文档继续向下。

后端校验 trace、文档和 parent，自动计算 depth 并记录服务端耗时。没有 trace 的 MCP read 会被拒绝。

## 5. Tasks 可观察链路

Tasks 外层列表只展示 `source=mcp` 的任务：

- 任务文本、项目、AI 工具、时间。
- 候选文档数、实际 read 数、MCP 总耗时。

任务详情展示：

- `prepare_task_context` 请求及返回候选文档。
- 每份候选文档是 `Read by AI` 还是 `Returned only`。
- 每次 `read_context_document` 的 document_id、parent_document_id 和耗时。

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
- 不把数据库作为项目文档的唯一编辑源。
- 不提供开发者命令行产品入口。
