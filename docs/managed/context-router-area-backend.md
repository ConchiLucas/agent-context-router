# 后端路由

本文件用于把后端接口、检索、trace、CLI 和 MCP 类任务路由到合适上下文。

## 适用任务

- 修改 FastAPI 接口。
- 调整 `ctx prepare`、`ctx read`、trace 或反馈逻辑。
- 修改 CLI、MCP 或上下文渲染。
- 排查后端服务、API 响应或检索排序。

## 子路由

- `backend_api`：FastAPI 路由和请求响应模型。
- `context_prepare`：任务上下文准备、检索和 Markdown 渲染。
- `trace_recording`：prepare/read/feedback 的记录与观察。
- `cli_mcp`：CLI 命令和 MCP 工具入口。

## 下一步

- 需要接口链路时，直接读 `backend/src/context_router/api/`。
- 需要 CLI/MCP 时，直接读 `backend/src/context_router/cli.py` 和 `backend/src/context_router/mcp_server.py`。
- 需要检索逻辑时，直接读 `backend/src/context_router/services/`。
- 需要历史记录时，读 `docs/development-details/CODE_CHANGE_LOG.md`。

修改后端代码后，按开发规范使用 Docker Compose 重启后端服务。
