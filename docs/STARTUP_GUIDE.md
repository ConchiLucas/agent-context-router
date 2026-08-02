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

携带任意 `Origin` 或浏览器 Fetch Metadata（`Sec-Fetch-Mode` / `Sec-Fetch-Site`）的请求由后端只读中间件限制为 `GET/HEAD/OPTIONS`，以及五类不会修改配置的安全 `POST`：数据源连接测试、数据源密码按需查看、MCP 接入测试、Workspace prepare 预览和 Workspace 刷新。刷新只重建文档缓存与派生搜索索引；其他浏览器配置写请求返回 `405 management_read_only`。本机 AI 或运维调用方不携带这些浏览器请求头，仍可使用既有受 Schema、Service 和 Repository 校验的本地 API 维护配置；这只是回环单用户部署下的调用边界，不替代身份认证。

## 手动启动控制面与 Host Runner

需要通过 MCP 启动或增量更新目标 Workspace 时，在本仓库根目录手动执行：

```bash
./scripts/start-local-stack.sh
./scripts/status-local-stack.sh
./scripts/stop-local-stack.sh
./scripts/stop-local-stack.sh --all
```

`start-local-stack.sh` 启动当前目录的 Docker Compose，等待后端健康后，再把宿主机 Host Runtime Runner 作为独立后台进程启动并等待心跳。普通 `stop-local-stack.sh` 只停止 Runner；`--all` 还停止本仓库 Compose。这里没有 Docker/launchd 开机自启，电脑重启后需要使用编排能力时再手动启动。

Runner 是“所有项目都在 Docker Compose 内运行”规则的唯一宿主机例外：它不运行本项目业务前后端，只负责从回环控制面领取已校验快照，并调用目标 Workspace 自己的部署脚本。Token 默认生成在 `.runtime-runner/runner.token`，目录权限为 `0700`、文件权限为 `0600`；PID 和 Runner 日志位于同一目录。控制面 URL 必须是 loopback 地址，Token 不得写入 Git、日志或命令参数。

可选配置：

```text
CONTEXT_ROUTER_RUNTIME_HOST_ROOT=/absolute/path/to/runtime
CONTEXT_ROUTER_WORKSPACE_HOST_ROOT=/Users/conchi/workforce
CONTEXT_ROUTER_CONTROL_URL=http://127.0.0.1:49173
CONTEXT_ROUTER_RUNTIME_RUNNER_HEARTBEAT_TTL_SECONDS=30
CONTEXT_ROUTER_RUNTIME_RUNNER_LEASE_SECONDS=30
CONTEXT_ROUTER_RUNTIME_EXECUTION_TIMEOUT_SECONDS=1800
```

每个目标 Workspace 根目录自行保留一份被 Git 忽略的 `.env.local`，作为这台电脑唯一的数据库、Redis、MinIO 等差异配置入口。Context Router 只保存部署脚本、项目顺序和路径策略，不读取、上传、物化或记录 `.env.local` 的内容；目标仓库的启动脚本负责校验和加载它。

## 工作区挂载

后端需要读取用户填写的 Workspace 绝对根目录、可选的 Workspace 根 `AGENTS.md`，以及各项目独立配置的 `document_relative_path`。新项目文档入口统一位于 Workspace 的 `docs/` 层级下，源码 `relative_path` 只用于项目定位和 cwd 路由。Compose 将宿主机工作区根目录只读挂载到容器 `/workspace`：

```text
CONTEXT_ROUTER_WORKSPACE_HOST_ROOT=/Users/conchi/workforce
```

Workspace 启动配置、Project 快速/完整更新配置和运行策略以 PostgreSQL 为真源，并由后端物化到独立运行目录；浏览器页面只查看配置和历史运行状态，不提供保存、物化或执行按钮。Compose 默认把宿主机 `./.runtime-runner` 挂载到容器 `/runtime`；可以通过 `CONTEXT_ROUTER_RUNTIME_HOST_ROOT` 改为其他绝对目录，运行快照不会写入目标项目源码目录。

Host Runtime Runner 只执行快照根目录下固定的 `deploy.sh`。执行前会校验 Manifest、文件哈希、Workspace/Project 相对路径、软链接边界和固定脚本名；步骤按项目顺序串行执行，首个失败后停止并把后续步骤标记 skipped，不自动清理目标容器。服务必须继续绑定回环地址，不得在缺少 HTTPS 和鉴权时对外暴露。

后端收到宿主机绝对路径后，会将该前缀替换为 `/workspace` 再读取文件。目标文件必须位于挂载的工作区中。

Compose 不声明或自动创建任何工作空间和项目；浏览器只负责查看，配置由本机 AI 或运维通过既有受校验 API 维护。MCP 接入仍可使用以下环境变量：

```text
CONTEXT_ROUTER_PUBLIC_MCP_URL=http://127.0.0.1:49173/mcp
CONTEXT_ROUTER_MCP_TEST_TIMEOUT_SECONDS=15
```

修改挂载路径或上述接入变量后需要重建容器。

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
CONTEXT_ROUTER_DATABASE_PAYLOAD_REQUEST_BYTES=1000000
CONTEXT_ROUTER_DATABASE_PAYLOAD_RESPONSE_BYTES=1000000
CONTEXT_ROUTER_DATABASE_PAYLOAD_HARD_MAX_BYTES=4000000
CONTEXT_ROUTER_DATABASE_PAYLOAD_TTL_DAYS=7
CONTEXT_ROUTER_DATABASE_PAYLOAD_CLEANUP_INTERVAL_SECONDS=3600
```

项目数据库关联自己的行数、字节数和超时限制会与查询全局值取更严格者。数据库 MCP 出入参详情默认自动采集，`DATABASE_PAYLOAD_*` 控制两个数据库 MCP 工具的本地详情快照：请求和最终 MCP 响应默认分别最多保存 1 MB，任何配置都不能超过 4 MB，默认保留 7 天，并在后端启动及调用期间按节流周期清理。授权记录归属 Project，但 `mcp_alias` 在 Workspace 内唯一，新 Workspace task 可以使用所有子项目在 prepare 中返回的 alias。修改这些值后重启 backend。

配置了 Workspace 环境选择器后，`prepare_task_context` 可选传入 `environment='test'` 或 `environment='uat'`。显式传入只为本次 task 固化所选环境并记录 `task_explicit`，不会修改 Workspace 当前环境；省略参数时使用 Workspace 当前环境并记录 `workspace_default`。数据库摘要、`environment_config` 和后续数据库工具都按 task 固化的环境解析。

本机 AI 或运维通过受校验 API 保存环境映射、保存 TEST/UAT 通用 JSON 或切换 Workspace 当前环境时，都会递增同一个 revision；无论 task 使用 `workspace_default` 还是 `task_explicit`，revision 不一致时数据库调用都会返回 `environment_changed`，需要重新 prepare。浏览器环境详情只读取映射、JSON 和默认环境，不修改它们。没有配置环境选择器的单环境 Workspace 在省略 `environment` 时保持原有数据库授权行为；显式传参不会隐式创建选择器，而是返回 `environment_not_configured`。

Workspace 可以独立保存 TEST/UAT 两份 JSON 对象；首次保存默认选择 UAT，不要求先配置数据库映射，数据库会继续沿用原有 Workspace alias。两份 JSON 合计最多 256 KiB、最多嵌套 20 层，超出 JavaScript 安全整数范围的值请改用字符串。task 所选环境的 JSON 会作为 `environment_config` 只返回给可信本机 MCP 调用方。该字段可按明确业务需要保存 MQ、Redis、MinIO、ES 等组件的地址和访问凭据，内容以明文 JSONB 保存在本地；严禁把实际值写入日志、开发文档、链路摘要或示例输出。

## PostgreSQL 与 migration

在 `.env` 中配置宿主机 PostgreSQL：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/context_router
```

首次启动或 migration 变化后执行：

```bash
docker compose exec backend uv run alembic upgrade head
```

当前 migration head 为 `20260802_0023`。`0013` 引入 Workspace 与项目相对路径；`0014` 增加 `frontend/backend` 项目类型、移除 Project enabled、把 `mcp_alias` 唯一范围提升到 Workspace，并为新 task 增加 Workspace scope；`0015` 增加工作空间级 Markdown 的独立词法搜索索引；`0016` 将项目源码 `relative_path` 与文档入口 `document_relative_path` 拆分；`0017` 增加按项目和更新模式持久化的运行配置文件；`0018` 增加 Runtime Runner 异步执行记录；`0019` 增加 Workspace TEST/UAT 数据库映射和 task 环境 revision；`0020` 增加 TEST/UAT 通用环境 JSON；`0021` 为 task 增加 `database_environment_selection`；`0022` 移除 Workspace、数据源、项目数据库授权和环境映射配置的启停字段与相关索引；`0023` 增加 Workspace 启动文件、运行策略、原子操作步骤、租约和 Host Runner 实例。旧 task 保持 `scope='project'` 兼容，迁移同时保留 Workspace/活动项目快照和兼容 `agents_path`。

PostgreSQL 保存 Workspace、Project 类型、源码相对路径、文档入口相对路径、数据源、数据库清单、项目数据库关联及 Workspace 唯一 `mcp_alias`、可选 TEST/UAT 数据库映射与通用 JSON、带 scope/环境/revision/选择模式的 MCP task、read call、文档顺序、数据库调用审计元数据，以及可重建的文档搜索分块与索引状态。文档树和 Markdown 原文仍从磁盘重建，文档工具完整出入参不持久化；`search_database_objects` 和 `execute_database_query` 自动保存有界、可过期的详情快照，供本机链路页面按需查看。后端启动时恢复工作空间和全部项目配置，并从磁盘重建每个项目的内存树与匹配版本词法索引；路径失效的项目仍保留在页面并显示错误。

数据库未配置时后端和 `/health` 仍可启动，但不会自动创建默认 Workspace/Project，且 task_id 持久化、prepare/search/read 的完整 MCP 工作流、Workspace MCP JSON 预览和持久化调用记录不可用。文档搜索不会降级为进程内扫描。业务数据源离线不会阻止后端启动，也不会阻止 Workspace 文档 prepare/search/read；连接只在测试、同步、对象搜索或查询时延迟建立。

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
