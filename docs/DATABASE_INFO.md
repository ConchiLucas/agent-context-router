# 数据库信息

本文件记录当前项目数据库信息。以后检查 bug、运行脚本、排查数据问题前，先阅读本文件。

## 当前默认数据库

项目代码默认连接本机 PostgreSQL：

```text
host: 127.0.0.1
port: 5432
database: context_router
user: conchi
password: conchi123456
```

SQLAlchemy 连接串：

```bash
postgresql+psycopg://conchi:conchi123456@127.0.0.1:5432/context_router
```

对应位置：

- `backend/src/context_router/config.py`
- `backend/.env.example`
- `backend/alembic.ini`

## Docker Compose 数据库

`docker-compose.yml` 中也包含一个项目专用 PostgreSQL 服务：

```text
service: postgres
image: postgres:16
host port: 54329
container port: 5432
database: context_router
user: context_router
password: context_router
```

宿主机访问连接串：

```bash
postgresql+psycopg://context_router:context_router@127.0.0.1:54329/context_router
```

Docker Compose 后端容器内访问连接串：

```bash
postgresql+psycopg://context_router:context_router@postgres:5432/context_router
```

## 表结构状态

当前项目不使用向量、embedding、pgvector 或 document chunk 表。

已知当前 migration 版本：

```text
20260719_0008
```

核心表：

```text
projects
documents
traces
trace_events
retrieval_hits
usage_cards
alembic_version
```

`projects` 支持父子项目层级：

```text
id
slug
name
root_path
docs_path
last_synced_at
last_sync_status
last_sync_summary
description
parent_project_id
created_at
updated_at
```

`documents` 保存完整 Markdown 正文：

```text
id
project_id
title
source_path
doc_type
area
tags
status
content_markdown
is_reachable
graph_depth
created_at
updated_at
```

`root_path` 只用于 cwd 识别代码项目；唯一 `docs_path` 定位 `/documents` 下的直接子目录。`last_sync_summary` 保存 indexed、reachable、orphan、broken_links、pruned 计数。

`documents.status="removed"` 是保留历史 Task 引用的 tombstone：普通 Documents 列表默认排除，但旧 `retrieval_hits` 和事件仍能展示标题。tombstone 的 `is_reachable=false`、`graph_depth=null`。

`document_links` 保存同步解析出的 Markdown 链接；无法解析的目标保留 `target_document_id=null`，用于 Web 展示 broken link。

当前受管文档来自映射根的 `AGENTS.md` 和 `docs/**/*.md`。入口强制为 `agent_index`，其余类型来自 front matter。

```text
agent_index
routing_index
usage_guide
usage_step
routing_guide
area_route
project_entry_guide
```

配置文件、表结构 SQL、manifest 和源码细节不作为常规受管文档入库，需要时让 AI 直接读取项目目录。

`traces` 保存一次 MCP 上下文准备过程和入口路由信息：

```text
id
project_id
task
cwd
area
entrypoint_path
entrypoint_rule
route_hint
source
agent_name
created_at
```

`trace_events` 保存客观 MCP 调用事件。当前运行时主要写入 `prepare` 和 `read`，payload 中可包含 `duration_ms`、`document_id`、`parent_document_id` 和 `depth`。

`retrieval_hits` 保存 prepare 返回的 AGENTS.md 入口，并维持历史引用。Tasks 详情把它与 read 事件对照为 `Entry read` 或 `Entry returned`。

`usage_cards` 是旧版本 Usage 功能的历史表。当前没有对应 API 或页面，migration 和表暂时保留兼容：

```text
id
slug
title
description
content_markdown
sort_order
is_builtin
created_at
updated_at
```

## 常用命令

通过 Docker Compose 后端环境执行 migration：

```bash
docker compose run --rm backend uv run alembic upgrade head
```

查看 compose 数据库 migration 版本：

```bash
docker compose exec -T postgres psql -U context_router -d context_router -c "SELECT version_num FROM alembic_version;"
```

查看 compose 数据库表：

```bash
docker compose exec -T postgres psql -U context_router -d context_router -c "\dt"
```

## 使用原则

- 检查 bug 或运行脚本前，先确认要连接的是本机默认数据库还是 Docker Compose 数据库。
- 后端容器内脚本优先使用 compose 内部连接串。
- 不要把宿主机脚本作为项目的启动或验证方式。
- 表结构变更必须通过 Alembic migration 管理。
