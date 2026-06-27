# 启动与开发规范

## 服务管理

- 本地服务生命周期统一使用 Docker Compose 管理。
- 如果修改了后端代码，在验证前需要用 Docker Compose 重启后端：

```bash
docker compose restart backend
```

- 如果用户要求启动前后端，使用 Docker Compose 启动：

```bash
docker compose up -d backend frontend
```

- 如果前后端已经在运行，而用户仍要求启动前后端，则改为重启：

```bash
docker compose restart backend frontend
```

## 验证

- 修改后端后，通过 Docker Compose 的后端环境运行检查：

```bash
docker compose run --rm backend uv run --extra dev pytest -q
docker compose run --rm backend uv run --extra dev ruff check .
docker compose run --rm backend uv run --extra dev ruff format --check .
```

- 修改前端后，通过 Docker Compose 的前端环境运行检查：

```bash
docker compose run --rm frontend npm run lint
docker compose run --rm frontend npm run build
```

## 数据库

- 本地开发优先使用项目已配置的 PostgreSQL 数据库连接。
- 表结构变更必须通过 Alembic migration 表达。
- 通过后端服务环境执行数据库迁移：

```bash
docker compose run --rm backend uv run alembic upgrade head
```

## 修改原则

- 修改范围应聚焦在用户请求的行为上。
- 不要删除或重写与当前任务无关的用户改动。
- 如果本地开发命令发生变化，需要同步更新 README 或本规范文档。
