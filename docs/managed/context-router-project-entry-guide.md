# 子项目入口文档说明

每个子项目的 AGENTS.md 或 AI_CONTEXT_INDEX.md 应保持简短，只列稳定文档和适用任务。文档源留在子项目仓库，由 Context Router 同步索引。

## 已知子项目入口

| 子项目 | 入口 document_id 类型 | 适用任务 |
| --- | --- | --- |
| Java / Go / Python 后端 | `*-agents-md`、`*-ai_context_index-md` | 服务职责、数据库、API 和启动规则 |
| React / Vue 前端 | `*-agents-md`、`*-ai_context_index-md` | 页面结构、接口链路和开发规范 |
| 多项目 workspace | `*-subprojects-overview`、`*-flow-overview` | 子项目职责和跨服务流转 |

维护时优先补清楚 document_id、适用任务和下一层关系，不要在入口复制完整正文。
