# 开发大纲

修改代码前先按任务读取对应文档，不要一次加载全部说明。

## 必读顺序

1. [启动与开发规范](./STARTUP_GUIDE.md)：所有启动、测试、lint、build、migration 都走 Docker Compose。
2. 按任务选择下表中的一份或两份文档。
3. 涉及历史取舍时再读 `development-details/`。

## 任务路由

| 任务 | 文档 | 主要代码 |
| --- | --- | --- |
| 产品目标、功能边界 | [业务功能说明](./BUSINESS_FEATURES.md) | `backend/src/context_router/api/`, `frontend/app/` |
| 页面到 API、数据库链路 | [前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `frontend/lib/api.ts`, `backend/src/context_router/api/` |
| 数据库、migration、排查数据 | [数据库信息](./DATABASE_INFO.md) | `backend/src/context_router/db/`, `backend/alembic/` |
| MCP 工具协议 | [业务功能说明](./BUSINESS_FEATURES.md) | `backend/src/context_router/mcp_server.py` |
| 文档映射、同步和读取策略 | [前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `backend/src/context_router/services/document_mapping.py`, `document_graph.py` |
| Tasks 列表与调用链详情 | [前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `frontend/app/tasks/`, `frontend/components/task-*` |
| 项目和文档网页管理 | [业务功能说明](./BUSINESS_FEATURES.md) | `frontend/app/projects/`, `backend/src/context_router/api/projects.py` |

## 当前架构约束

- 产品入口是 MCP + Web；HTTP API 仅为内部实现。
- MCP 只有 `prepare_task_context` 和 `read_context_document` 两个无状态工具。
- 每次 prepare 都生成独立 trace，不共享“当前任务”。
- read 必须显式携带 trace_id；parent_document_id 只能指向同一 trace 中已读文档。
- 项目默认按 cwd 的最长 root path 匹配。
- Tasks 页面只展示 MCP 来源的任务和客观事件，不记录反馈或停止阅读原因。
- prepare 只返回映射文档项目的 AGENTS.md；后续 read 只能沿已读 parent 的直接链接继续。
- 历史数据库列和 migration 暂不删除。
