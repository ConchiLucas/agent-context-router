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

Compose 的前端和后端宿主机端口都显式绑定 `127.0.0.1`，不会默认监听局域网网卡。后端 CORS 只允许 `http://127.0.0.1:49174` 和 `http://localhost:49174`；本项目当前定位为本机工具，不提供应用层鉴权。若未来需要远程访问，应先补 HTTPS、鉴权和新的 Origin 配置，而不是直接改成公网绑定。

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

`CONTEXT_ROUTER_PUBLIC_MCP_URL` 只用于接入面板生成 Codex 和 Antigravity 配置；后端容器通过固定的 `http://127.0.0.1:8000/mcp` 对自身执行真实协议测试。修改该变量不会改变 Compose 的回环绑定，也不会增加 HTTPS 或鉴权；当前版本不支持远程暴露。若未来设计远程部署，需要先完成安全评审和相应实现，再把公开地址设置为客户端实际可访问的 URL。

数据库 MCP 的可选全局硬上限使用同一 `CONTEXT_ROUTER_` 前缀：

```text
CONTEXT_ROUTER_DATABASE_TOOLS_ENABLED=true
CONTEXT_ROUTER_DATABASE_MAX_ROWS=5000
CONTEXT_ROUTER_DATABASE_MAX_RESULT_BYTES=4000000
CONTEXT_ROUTER_DATABASE_MAX_QUERY_TIMEOUT_MS=30000
CONTEXT_ROUTER_DATABASE_MAX_CACHED_CONNECTORS=16
CONTEXT_ROUTER_DATABASE_MAX_CONCURRENCY_PER_SOURCE=4
CONTEXT_ROUTER_DATABASE_SCHEMA_RESULT_BYTES=1000000
```

项目数据库关联自己的行数、字节数和超时限制会与这些全局值取更严格者。修改全局限制后重启 backend。

## PostgreSQL 与 migration

在 `.env` 中配置宿主机 PostgreSQL：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/context_router
```

首次启动或 migration 变化后执行：

```bash
docker compose exec backend uv run alembic upgrade head
```

PostgreSQL 保存项目、数据源、数据库清单、项目数据库关联及 `mcp_alias`、MCP task、read call、文档顺序和数据库调用审计元数据，不保存文档树、Markdown 正文、完整 SQL、SQL 参数或查询结果。后端启动时恢复项目配置，并为启用项目从磁盘重建内存树；路径失效的项目仍保留在页面并显示错误。

数据库未配置时后端和 `/health` 仍可启动，项目配置退化为当前进程内存；但 task_id 持久化、prepare/read 的完整 MCP 工作流、卡片 JSON 预览和持久化调用记录不可用。业务数据源离线不会阻止后端启动，也不会阻止文档 prepare/read；连接只在测试、同步、对象搜索或查询时延迟建立。

## Docker Desktop 与公司 VPN 数据库

macOS 主机可通过公司 VPN 访问数据库时，Docker Desktop 虚拟网络不一定继承对应路由。典型现象是宿主机 TCP 探测成功，而 backend 容器连接同一内网地址超时。此时使用仓库内的 localhost TCP relay：

```bash
launchctl bootstrap "gui/$(id -u)" \
  ./launchd/com.conchi.agent-context-router.vpn-relay.plist
```

该 relay 只监听宿主机 `127.0.0.1`，不会暴露到局域网；Docker Desktop 仍可通过 `host.docker.internal` 访问。当前映射为：

| 容器数据源地址 | 宿主机经 VPN 转发到 |
| --- | --- |
| `host.docker.internal:48306` | `192.168.0.219:8306`（Test/UAT MySQL） |
| `host.docker.internal:49030` | `192.168.0.227:9030`（ODS） |

relay 由当前 macOS 登录会话的 launchd 托管，Context Router 或 Codex 重启不会中断它。查看与停止：

```bash
launchctl print "gui/$(id -u)/com.conchi.agent-context-router.vpn-relay"
launchctl bootout "gui/$(id -u)/com.conchi.agent-context-router.vpn-relay"
```

如需登录后自动加载，可把 plist 安装到 `~/Library/LaunchAgents/`。上游 VPN 断开时 relay 仍保持监听，但数据库连接测试会失败；VPN 恢复后无需重启 relay。

## ClickHouse integration profile

根 Compose 提供固定版本 `clickhouse/clickhouse-server:24.8.14.39-alpine` 的 `clickhouse-test` 服务，只在 `integration` profile 中启动，不属于日常前后端依赖：

```bash
docker compose --profile integration up -d --wait clickhouse-test
docker compose exec backend uv run --extra dev pytest -q -m clickhouse
docker compose --profile integration stop clickhouse-test
```

集成测试会创建临时数据库对象和只读用户，覆盖 ping、数据库发现、Unicode 表名、table/view/column/index 渐进搜索、行数截断、数据库侧拒写和超时映射。不要把 `clickhouse-test` 的测试账号用于真实数据源。

从 backend 容器访问宿主机 ClickHouse 时，数据源 Host 填 `host.docker.internal`；访问 Compose 内的测试 ClickHouse 时使用服务名 `clickhouse-test`。ClickHouse HTTP 默认端口是 8123，启用 secure 且未填端口时 Connector 默认使用 8443。

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

默认后端单元测试不要求 ClickHouse 服务在线；未启动 integration profile 时，带 `clickhouse` marker 的真实集成用例会跳过。发布前或修改 ClickHouse Connector 后，应显式启动 profile 并执行上面的 marker 测试。
