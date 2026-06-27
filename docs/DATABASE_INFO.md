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
20260627_0005
```

核心表：

```text
projects
documents
traces
trace_events
retrieval_hits
alembic_version
```

`projects` 支持父子项目层级：

```text
id
slug
name
root_path
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
created_at
updated_at
```

当前受管文档只保存稳定入口和说明类文档。当前主要类型：

```text
agent_index
routing_index
```

配置文件、表结构 SQL、manifest 和源码细节不作为常规受管文档入库，需要时让 AI 直接读取项目目录。

`traces` 保存一次上下文准备过程和入口路由信息：

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
- 宿主机直接运行脚本时优先使用当前默认数据库连接串。
- 表结构变更必须通过 Alembic migration 管理。
