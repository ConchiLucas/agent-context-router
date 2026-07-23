# 子项目入口文档说明

每个项目的 AGENTS.md 应保持简短，在 `## 下级文档` 标准两列表格中只列稳定文档和适用任务。文档源留在项目仓库；Context Router 添加或刷新项目时递归读取并原子替换内存文档树，不把 Markdown 正文持久化到数据库。

## 已知子项目入口

| 子项目 | 入口 document_id 类型 | 适用任务 |
| --- | --- | --- |
| Java / Go / Python 后端 | `*-agents-md`、`*-ai_context_index-md` | 服务职责、数据库、API 和启动规则 |
| React / Vue 前端 | `*-agents-md`、`*-ai_context_index-md` | 页面结构、接口链路和开发规范 |
| 多项目 workspace | `*-subprojects-overview`、`*-flow-overview` | 子项目职责和跨服务流转 |

维护时优先补清楚显式 title、summary、相对路径、适用任务和下一层关系，不要在入口复制完整正文。项目数据库授权独立保存在控制面数据库，不应把 Host、账号或密码写入 AGENTS.md。
