# 启动与开发规范

## 强制规则

- 本项目在宿主机直接启动前后端，不要用 Docker Compose 启动服务。
- 后端用 `uv` + `uvicorn`，前端用 `npm run dev`。
- 后续自测、重启、测试、lint、build、migration 都在宿主机执行。
- `docker-compose.yml` 只是历史文件，不是当前启动方式。

## 依赖

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- 本机 PostgreSQL，默认连接见 [数据库信息](./DATABASE_INFO.md)

## 首次准备

在仓库根目录：

```bash
cp backend/.env.example backend/.env
```

`backend/.env` 默认使用本机 PostgreSQL：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql+psycopg://conchi:conchi123456@127.0.0.1:5432/context_router
```

文档目录是本机路径，不是容器挂载。后端从 `backend/` 启动时，可在 `backend/.env` 增加：

```text
CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT=../document-sources
CONTEXT_ROUTER_SCRIPTS_SNAPSHOT_ROOT=../script-sources
```

`document-sources/` 下每个子目录必须包含根 `AGENTS.md` 和 `docs/`。Projects 页面只选择该文档根的直接子目录名。

安装依赖并执行 migration：

```bash
cd backend && uv sync --extra dev
cd backend && uv run alembic upgrade head
cd frontend && npm install
```

## 启动

开两个终端，都在仓库根目录操作。

后端：

```bash
cd backend
uv run uvicorn context_router.main:create_app --factory --host 0.0.0.0 --port 49173
```

前端：

```bash
cd frontend
CONTEXT_ROUTER_INTERNAL_API_URL=http://127.0.0.1:49173 \
NEXT_PUBLIC_CONTEXT_ROUTER_API_URL=http://127.0.0.1:49173 \
npm run dev -- --hostname 0.0.0.0 --port 49174
```

- Web：`http://127.0.0.1:49174`
- API：`http://127.0.0.1:49173`
- PostgreSQL：`127.0.0.1:5432`

## 重启

- 修改后端后，停掉后端终端里的 `uvicorn`，再按上面的后端命令重新启动。
- 用户要求启动前后端时：没有在跑就按上面启动；已经在跑就先停再启。
- 不要用 `docker compose restart`。

## 验证

修改后端后，在 `backend/` 执行：

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

修改前端后，在 `frontend/` 执行：

```bash
npm run lint
npm test
npm run build
```

`npm run build` 在一次性临时副本中构建，不会覆盖正在运行的开发服务 `.next` 缓存或改写源码配置。

根目录 `make test`、`make lint`、`make build` 也是同一套宿主机命令。

## 数据库

- 本地开发使用本机 PostgreSQL。
- 表结构变更必须通过 Alembic migration 表达。
- 在 `backend/` 执行迁移：

```bash
uv run alembic upgrade head
```

## 修改原则

- 修改范围应聚焦在用户请求的行为上。
- 不要删除或重写与当前任务无关的用户改动。
- 如果本地开发命令发生变化，需要同步更新 README 或本规范文档。
