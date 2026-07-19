# 后端路由

## 适用任务

- FastAPI 内部 API、MCP 工具协议。
- cwd 项目识别、候选检索和排序。
- prepare/read 事件、父子文档链路和耗时。

## 代码入口

| 路径 | 用途 |
| --- | --- |
| `backend/src/context_router/mcp_server.py` | 两个无状态 MCP 工具 |
| `api/context.py` | prepare 内部 API |
| `api/documents.py` | read、同步和文档列表 |
| `api/traces.py` | Tasks 列表与详情数据 |
| `services/project_resolution.py` | project/cwd 识别 |
| `services/retrieval.py` | 候选检索和排序 |

产品层没有 CLI、反馈和 Usage runtime。
