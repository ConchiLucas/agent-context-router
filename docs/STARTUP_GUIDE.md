# 启动与开发规范

## 强制规则

- 本项目只允许使用当前目录下的 `docker-compose.yml` 管理服务。
- 不要直接在宿主机运行 `uvicorn`、`next dev`、`npm run dev`、`uv run ...` 等服务启动命令。
- 后续自测、启动、重启、测试、lint、build、migration 都优先通过 Docker Compose 执行。
- 如果为了排查必须临时运行宿主机命令，需要在回复中说明原因，并且不能把它作为项目启动方式。

## 开机自启

`docker-compose.yml` 中的 `postgres`、`backend`、`frontend` 都配置了：

```yaml
restart: unless-stopped
```

这表示容器创建并启动过一次后，只要 Docker Desktop 或 Docker daemon 随系统启动，容器会自动恢复运行。首次启用或修改 compose 配置后，在项目根目录执行：

```bash
docker compose up -d
```

Mac 上还需要确认 Docker Desktop 已开启开机启动；否则系统启动时 Docker 没有运行，容器也不会被自动拉起。

## 服务管理

- 本地服务生命周期统一使用 Docker Compose 管理，并且命令都在项目根目录执行。
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
docker compose exec backend uv run --extra dev pytest -q
docker compose exec backend uv run --extra dev ruff check .
docker compose exec backend uv run --extra dev ruff format --check .
```

- 修改前端后，通过 Docker Compose 的前端环境运行检查：

```bash
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

## 数据库

- 本地开发优先使用项目已配置的 PostgreSQL 数据库连接。
- 表结构变更必须通过 Alembic migration 表达。
- 通过后端服务环境执行数据库迁移：

```bash
docker compose exec backend uv run alembic upgrade head
```

## 修改原则

- 修改范围应聚焦在用户请求的行为上。
- 不要删除或重写与当前任务无关的用户改动。
- 如果本地开发命令发生变化，需要同步更新 README 或本规范文档。
