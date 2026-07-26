# 工作空间与子项目入口文档说明

Workspace 根目录可以放置一个工作空间级 `AGENTS.md`，用于跨项目说明和统一业务链路；Workspace 下每个 Project 仍使用自己的 `AGENTS.md`。两类入口都应保持简短，在 `## 下级文档` 标准两列表格中只列稳定文档和适用任务。根入口不存在时使用合成工作空间根；刷新时递归构建根入口和所有 Project 文档树，并在全部成功后原子替换 Workspace 聚合树。Markdown 原文不持久化到数据库，只保存可由原文重建的 Workspace/Project 规范化词法检索分块。

## 已知子项目入口

| 子项目 | 入口 document_id 类型 | 适用任务 |
| --- | --- | --- |
| Java / Go / Python 后端 | `*-agents-md`、`*-ai_context_index-md` | 服务职责、数据库、API 和启动规则 |
| React / Vue 前端 | `*-agents-md`、`*-ai_context_index-md` | 页面结构、接口链路和开发规范 |
| 多项目 workspace | `*-subprojects-overview`、`*-flow-overview` | 子项目职责和跨服务流转 |

维护时优先补清楚显式 title、summary、相对路径、适用任务和下一层关系，不要在入口复制完整正文。Workspace 根入口与 Project 重复引用同一物理文档时只保留 Workspace 所有权；Project 之间仍由最深项目拥有。Project 数据库授权独立保存在控制面数据库，由 Workspace 汇总展示和授权给 Workspace task；不应把 Host、账号或密码写入 AGENTS.md。
