# 启动与开发规范

## 强制规则

- 前后端服务、测试、lint 和 build 都通过当前目录的 `docker-compose.yml` 执行。
- 不在宿主机直接运行 `uvicorn`、`next dev`、`pytest` 或 `npm run build`。
- 修改后端代码后，验证前执行 `docker compose restart backend`。
- 使用宿主机已有的 PostgreSQL；migration 仍通过后端 Docker Compose 容器执行。

## 启动

```bash
docker compose up -d --force-recreate backend frontend
```

服务端口：

| 服务 | 地址 |
| --- | --- |
| Frontend | `http://127.0.0.1:49174` |
| Backend | `http://127.0.0.1:49173` |
| OpenAPI | `http://127.0.0.1:49173/docs` |
| MCP | `http://127.0.0.1:49173/mcp` |

服务均配置 `restart: unless-stopped`。

## 工作区挂载

后端需要读取用户填写的 `AGENTS.md` 绝对路径。Compose 将宿主机工作区根目录只读挂载到容器 `/workspace`：

```text
CONTEXT_ROUTER_WORKSPACE_HOST_ROOT=/Users/conchi/workforce
```

后端收到宿主机绝对路径后，会将该前缀替换为 `/workspace` 再读取文件。目标文件必须位于挂载的工作区中。

默认项目通过以下环境变量配置：

```text
CONTEXT_ROUTER_DEFAULT_PROJECT_NAME=攀枝花多式联运
CONTEXT_ROUTER_DEFAULT_AGENTS_PATH=/Users/conchi/workforce/.../AGENTS.md
CONTEXT_ROUTER_PUBLIC_MCP_URL=http://127.0.0.1:49173/mcp
CONTEXT_ROUTER_MCP_TEST_TIMEOUT_SECONDS=15
```

修改挂载路径或默认项目后需要重建容器。

环境变量默认项目属于声明式启动配置：如果在页面删除了同一路径项目，但 `CONTEXT_ROUTER_DEFAULT_AGENTS_PATH` 仍然存在，后端下次启动时会重新写入该项目；需要永久移除时同时清除默认项目环境变量。

`CONTEXT_ROUTER_PUBLIC_MCP_URL` 用于接入面板生成 Codex 和 Antigravity 配置；后端容器通过固定的 `http://127.0.0.1:8000/mcp` 对自身执行真实协议测试。部署到其他主机时必须把公开地址改为客户端实际可访问的 URL。

## PostgreSQL 与 migration

在 `.env` 中配置宿主机 PostgreSQL：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/context_router
```

首次启动或 migration 变化后执行：

```bash
docker compose exec backend uv run alembic upgrade head
```

数据库保存项目配置、MCP task、read call 和单次调用内的文档顺序，不保存文档树或 Markdown 正文。后端启动时恢复所有项目配置，并为启用项目从磁盘重建内存树；路径失效的项目仍保留在页面并显示错误。数据库未配置时后端仍可启动，但项目配置只在当前进程有效，prepare/read MCP、卡片 JSON 预览和调用记录不可用。

## 服务管理

```bash
docker compose restart backend
docker compose restart frontend
docker compose logs --tail=100 backend frontend
docker compose ps
```

## 后端验证

```bash
docker compose exec backend uv run --extra dev pytest -q
docker compose exec backend uv run --extra dev ruff check .
docker compose exec backend uv run --extra dev ruff format --check .
```

## 前端验证

```bash
docker compose exec frontend npm run lint
docker compose exec frontend npm test
docker compose exec frontend npm run build
```

`npm run build` 使用临时目录，不覆盖正在运行的 Next.js 开发缓存。
