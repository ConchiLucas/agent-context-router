# 数据库信息

当前版本使用宿主机已有的 PostgreSQL，持久化 MCP 任务和文档读取顺序；项目配置、文档树和 Markdown 正文仍保存在后端进程内。

## 连接配置

通过 `.env` 提供连接串，仓库不保存真实账号口令：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/context_router
```

后端容器通过 `host.docker.internal` 访问宿主机 PostgreSQL，不再启动项目自己的 PostgreSQL 容器。

## Migration

```bash
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run alembic current
```

## 当前表

| 表 | 用途 |
| --- | --- |
| `mcp_tasks` | 保存 prepare 产生的自增 task_id、项目快照、任务原文、cwd、Agent 和创建时间 |
| `mcp_document_read_calls` | 保存每次 read 的自增 read_call_id、task_id 和创建时间 |
| `mcp_document_read_items` | 保存单次 read 内的 position、文档 ID、相对路径、章节、状态和错误码 |
| `agent_context_router_alembic_version` | 当前精简应用的 migration 版本；与 context_router 库内历史 `alembic_version` 隔离 |

task_id 和 read_call_id 都由 PostgreSQL identity 自动生成；单次读取顺序来自请求数组 position。客户端不传序号，也不维护每任务计数器或锁。数据库不保存 Markdown 正文。数据库不可用时，项目页面和文档树仍能使用，但 MCP prepare/read、卡片 MCP JSON 和调用记录会返回明确错误。
