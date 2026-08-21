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
| Frontend | `http://127.0.0.1:49175` |
| Backend | `http://127.0.0.1:49173` |
| OpenAPI | `http://127.0.0.1:49173/docs` |
| MCP | `http://127.0.0.1:49173/mcp` |

服务均配置 `restart: unless-stopped`。

Compose 的前端和后端宿主机端口都显式绑定 `127.0.0.1`，不会默认监听局域网网卡。后端 CORS 只允许 `http://127.0.0.1:49175` 和 `http://localhost:49175`；本项目当前定位为本机工具，不提供应用层鉴权。若未来需要远程访问，应先补 HTTPS、鉴权和新的 Origin 配置，而不是直接改成公网绑定。

携带任意 `Origin` 或浏览器 Fetch Metadata（`Sec-Fetch-Mode` / `Sec-Fetch-Site`）的请求由后端中间件限制为读取、既有安全操作、按 Workspace/项目类型受限的容器批量重启或停止，以及系统文档 JSON 正文的受校验保存。浏览器不能新建或删除系统文档，也不能修改 key、顺序或 prepare 策略；其他控制面配置写请求返回 `405 management_read_only`。本机 AI 或运维调用方不携带这些浏览器请求头，仍可使用既有受 Schema、Service 和 Repository 校验的本地 API 维护配置；这只是回环单用户部署下的调用边界，不替代身份认证。

## Docker Desktop 与 Host Runner

Context Router 前后端仍只由本仓库 Docker Compose 管理，并使用
`restart: unless-stopped` 交给 Docker Desktop 恢复。Host Runner 不执行
`docker compose up`，也不负责启动本项目或目标 Workspace 的业务容器。需要使用运行编排时，
统一从宿主机脚本目录执行：

```bash
/Users/conchi/script/start-host-runner.sh start
/Users/conchi/script/start-host-runner.sh status
/Users/conchi/script/start-host-runner.sh stop
```

`start` 会等待 Docker Desktop 和 `http://127.0.0.1:49173/health` 就绪，随后只启动
宿主机 Runner。Runner 注册后会提交攀枝花白名单动作
`pzh.ensure-host-runtime`，默认 `environment=local`。该动作调用固定脚本
`/Users/conchi/script/ensure-panzhihua-host-runtime.sh`，只幂等保障已有容器、共享
Docker 网络、数据库 TCP 转发/代理和宿主机 Nginx 网关；不会构建镜像、创建业务
容器、拉取代码或执行 Fast/Full。

当前不自动安装 macOS LaunchAgent。以后设置开机启动时，LaunchAgent 只需执行
`/Users/conchi/script/start-host-runner.sh run`；Docker Desktop 的自动启动和容器
恢复仍由 Docker Desktop 自身配置负责。旧的 `scripts/start-local-stack.sh` 仅保留为
本仓库开发期手动组合入口，不作为开机入口。

Runner 会把后端重启期间的连接拒绝、连接重置和请求超时视为可重试错误，控制面恢复
后继续心跳和领取任务。Runner 是“所有项目都在 Docker Compose 内运行”规则的唯一
宿主机例外：它只执行不可变运行快照或白名单宿主机动作。Token 默认位于
`.runtime-runner/runner.token`，目录权限为 `0700`、文件权限为 `0600`；PID 和日志位于
同一目录。控制面 URL 必须是 loopback 地址，Token 不得写入 Git、日志或命令参数。

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

本机 AI 或运维保存 Project 运行配置时，后端会先用 PyYAML 解析非空的 `.yml/.yaml` 文件；语法错误响应只包含文件名、行号和列号，不回显文件内容，也不会覆盖数据库旧配置。Docker Compose 插值、服务定义和运行时依赖等语义仍由目标 Workspace 预检或实际执行负责。对于使用根 `.env.local` 作为唯一机器差异入口的 Workspace，推荐六个 Project 的 `fast/deploy.sh` 都保持为无凭据薄包装器，只调用目标仓库统一部署入口的单项目模式；Workspace `start/deploy.sh` 则调用同一入口的全量模式。

Host Runtime Runner 只执行快照根目录下固定的 `deploy.sh`。执行前会校验 Manifest、文件哈希、Workspace/Project 相对路径、软链接边界和固定脚本名；步骤按项目顺序串行执行，首个失败后停止并把后续步骤标记 skipped，不自动清理目标容器。Workspace 容器列表可按容器携带的稳定 `project_id` 直接触发该 Project 的 Fast 或 Full profile，不按容器名额外映射。服务必须继续绑定回环地址，不得在缺少 HTTPS 和鉴权时对外暴露。

容器列表中的 Fast/Full 按钮只在 Host Runtime Runner 在线时可用。浏览器提交单项目任务后，后端只校验并物化已登记的运行快照，再把 `project_update` 操作写入队列；后端容器不直接执行 Docker、Maven、JDK 或 Node 命令。宿主机 Runner 领取任务后，在项目当前本地工作树执行固定 `deploy.sh`，因此当前分支中的已提交、未提交和标准源码目录内未跟踪代码都会进入构建。

Runner 会向部署脚本注入 `RUNTIME_WORKSPACE_ID`、Project 步骤的 `RUNTIME_PROJECT_ID`、`RUNTIME_PROJECT_IDS`（Workspace 相对路径与 Project ID 的制表符分隔清单）、`RUNTIME_OPERATION_ID` 和 `RUNTIME_DEPLOY_MODE`。目标 Compose 服务统一写入同名 `runtime-runner.*` 标签；容器归属直接按 Workspace/Project ID 查询，不维护容器名或端口映射表。Workspace 启动脚本从 `RUNTIME_PROJECT_IDS` 解析各子项目 ID 后再调用项目部署入口。

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

每个 Workspace 独立维护环境列表，`local` 固定存在且为默认；`test`、`uat` 或其他环境只在该项目确有需要时由本机 AI/运维登记。`prepare_task_context` 可选传入任一已登记环境，显式传入记录 `task_explicit`，省略时固化 `local` 并记录 `workspace_default`。后续 `read_task_context`、数据库工具以及未显式传环境的中间件/表关联工具都继承 task 环境。

本机 AI 或运维通过受校验 API 调整环境与数据库关联时会递增共享 revision；task 快照 revision 不一致时数据库调用返回 `environment_changed`，需要重新 prepare。浏览器环境详情只读：页头下拉框选择查看环境，下面的 Nacos、MCP 流转和数据源汇总全部跟随切换。数据库记录自身不带环境名；环境只关联既有项目数据库授权，因此多个环境可以指向同一个数据库链接。

Workspace 可按任意已登记环境保存有界 JSON 对象，不要求先配置数据库关联；task 所选环境的 JSON 作为 `environment_config` 只返回给可信本机 MCP 调用方。全部环境 JSON 合计最多 256 KiB、最多嵌套 20 层，超出 JavaScript 安全整数范围的值请改用字符串。可按明确业务需要保存组件地址和访问凭据，但严禁把实际值写入日志、开发文档、链路摘要或示例输出。

需要从 Nacos 实时定位中间件时，由本机 AI/运维通过 `/api/workspaces/{workspace_id}/nacos-profiles/{environment}` 为已登记环境配置连接和声明式组件抽取规则。一个环境最多一个 Nacos 配置；`read_middleware_context` 显式环境优先，省略时继承 task 环境。由于 MCP 只绑定本机回环地址，工具默认返回账号、密码或 Token 等明文；只有明确传入 `reveal_secrets=false` 才脱敏。调用记录只保存数量、环境和警告，不保存响应值。

## PostgreSQL 与 migration

在 `.env` 中配置宿主机 PostgreSQL：

```text
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/context_router
```

首次启动或 migration 变化后执行：

```bash
docker compose exec backend uv run alembic upgrade head
```

当前 migration head 为 `20260821_0041`。`0041` 将 Apache Doris 加入数据源引擎枚举，并经 MySQL 协议执行只读查询；`0040` 增加动态 Workspace 环境注册表、固定 `local` 默认，移除逐 MCP 默认环境，并将 Nacos、数据库目标、环境 JSON、表关联和 task 快照统一到动态环境键；`0038` 增加表级更新入口子表并把插入入口的 kind 收成 `batch_insert` / `save_or_update` / `insert`；`0037` 增加表级插入入口子表；`0036` 增加表关联的四张投影表（版本、表、边、中间表折叠）；`0035` 增加带 LOCAL 默认值的白名单宿主机运行动作；`0029` 与 `0030` 保留为已回滚实验功能的兼容 revision 标记。

表关联页面的关联数据目前没有自动生成流水线，示例数据由可重复执行的种子脚本写入：

```bash
docker compose exec backend uv run python -m context_router.scripts.seed_table_relations \
  --workspace <workspace_id>
```

脚本按 `(workspace_id, environment)` 覆盖式重写，只有一个工作空间时可省略 `--workspace`。
用户给出表名要检查并补全时按 [按表名补全表关联](./development-details/table_relation_complete.md) 执行；字段对照见 [表关联种子怎么写](./development-details/table_relation_seed.md)。不要直接写投影表。

MySQL Connector 会从服务端版本标识区分 MySQL、MariaDB 和 Doris。Doris 使用 MySQL 协议接入，但目录读取不会启动其不支持的只读事务，也不会读取尚未验证兼容的 MySQL 约束/索引目录。

PostgreSQL 保存 Workspace、Project 类型、源码相对路径、文档入口相对路径、动态环境列表、数据源、数据库清单、项目数据库授权、环境到授权的关联、环境 Nacos/通用 JSON、带 scope/环境/revision/选择模式的 MCP task、read call、文档顺序、数据库调用审计元数据，以及可重建的文档搜索分块与索引状态。文档树和 Markdown 原文仍从磁盘重建，文档工具完整出入参不持久化；`search_database_objects` 和 `execute_database_query` 自动保存有界、可过期的详情快照，供本机链路页面按需查看。后端启动时恢复工作空间和全部项目配置，并从磁盘重建每个项目的内存树与匹配版本词法索引；路径失效的项目仍保留在页面并显示错误。

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

## 本机工作空间映射

复制 `.context-router/workspaces.example.yaml` 为被 Git 忽略的 `.context-router/workspaces.local.yaml`。key 使用数据库 `workspaces.id`，路径相对 `CONTEXT_ROUTER_WORKSPACE_HOST_ROOT`：

```yaml
version: 1
workspaces:
  workspace-id:
    visible: true
    main_path: company_workforce/example-main
    document_reader_paths:
      - company_workforce/example-other-branch
```

编辑后在工作空间页点击“重载本机映射”。`visible: false` 的卡片不显示；reader 目录只共享主目录文档，不能使用数据库或部署工具。复制数据库不会覆盖这份本机文件。

Context Router 的通用使用规则不写入目标工作空间。统一 JSON 文档和 MCP `tools/list` 菜单的展示方式见[系统文档维护说明](./SYSTEM_GUIDES.md)；prepare 不返回这些系统文档。

## 目标 Workspace 的文档与 deploy 文件同步

目标 Workspace 必须把运行入口保存在仓库内，Context Router 数据库只保存同步副本：

```text
deploy/context-router/manifest.yaml
deploy/context-router/workspace/start/deploy.sh
<project-root>/deploy/context-router/fast/deploy.sh
<project-root>/deploy/context-router/full/deploy.sh
```

每个入口都应能脱离 Context Router 直接运行；`WORKSPACE_HOST_ROOT` 和 `PROJECT_HOST_ROOT` 只能作为 Runtime Runner 的可选覆盖值。`.env.local`、Token、私钥等本机配置不得进入这些目录。

Workspace 详情的“文档与部署文件”只提供两种操作：从数据库全量覆盖主目录，或用主目录全量覆盖数据库。两者都会先确认删除原内容，不做差异、版本和冲突处理。数据库到本地只写主映射目录的 `docs/` 和固定 `deploy/context-router/` 目录；reader 目录不会写入，也不能执行部署。

Context Router 不可用时，其他 AI 应先阅读目标根 `AGENTS.md` 和 `deploy/context-router/README.md`，然后直接运行 Workspace 或 Project 的 `deploy.sh`。

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
