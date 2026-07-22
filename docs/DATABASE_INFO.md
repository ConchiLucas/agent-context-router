# 数据库信息

当前版本使用宿主机已有的 PostgreSQL，持久化项目配置、数据源管理配置、MCP 任务和文档读取顺序；文档树和 Markdown 正文仍只保存在后端进程内。

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
| `document_projects` | 保存稳定项目 ID、名称、项目类型、AGENTS.md 宿主机路径、启停状态和创建/更新时间 |
| `data_sources` | 保存物理数据库连接、独立数据源分类、数据库类型、启停状态和连接参数；密码不进入列表 API，仅可由本机页面通过独立 no-store 接口按需读取 |
| `data_source_databases` | 保存每个物理连接下可供项目选择的实际库、schema 或 SQLite 文件清单 |
| `project_databases` | 保存项目与具体数据库的多对多关联、别名、用途和只读/查询限制策略 |
| `mcp_tasks` | 保存 prepare 产生的自增 task_id、项目快照、任务原文、cwd、Agent 和创建时间 |
| `mcp_document_read_calls` | 保存每次 read 的自增 read_call_id、task_id 和创建时间 |
| `mcp_document_read_items` | 保存单次 read 内的 position、文档 ID、相对路径、章节、状态和错误码 |
| `agent_context_router_alembic_version` | 当前精简应用的 migration 版本；与 context_router 库内历史 `alembic_version` 隔离 |

task_id 和 read_call_id 都由 PostgreSQL identity 自动生成；单次读取顺序来自请求数组 position。客户端不传序号，也不维护每任务计数器或锁。数据库不保存文档树或 Markdown 正文。

项目创建、编辑、类型调整、启停和删除会同步写入 `document_projects`；未显式指定类型的项目默认归入“公司项目”。数据源以物理连接为单位保存在 `data_sources`，拥有与项目类型完全独立的分类字段，未显式指定时默认归入“本机电脑”；一个连接可包含多个库，项目通过“管理数据源”一次选择一个或多个连接下的多个库，并由 `project_databases` 持久化。批量保存会在一个事务中替换指定项目的关联，保留仍被选中的既有查询策略，新关联使用默认只读限制。当前版本不加密本地连接参数，列表 API 会过滤所有口令；编辑时口令留空会保留原值，只有用户点击眼睛时才通过 `POST /api/data-sources/{id}/reveal-password` 按需读取，并明确禁止缓存响应。MySQL/MariaDB/PostgreSQL 的数据库清单可从远端自动同步，已不存在或当前账号不可见的旧库只标记 `available=false`，不直接删除项目关联。

后端重启后按原项目 ID 恢复全部记录：启用项目重新读取磁盘文档，停用项目不建立缓存，路径失效的项目保留配置并记录加载错误。数据库不可用时，项目页面仍可依靠环境变量默认项目临时运行，但新增项目和数据源配置无法跨重启保存，MCP prepare/read、卡片 MCP JSON 和调用记录会返回明确错误。
