# 项目数据库上下文 MCP 技术设计

日期：2026-07-22

## 1. 背景与目标

Context Router 当前已经让 Codex、Antigravity 等 Agent 通过一个本地 MCP 服务完成：

- 根据 `cwd` 自动定位项目；
- 获取以 `AGENTS.md` 为入口的完整文档树；
- 按需读取完整 Markdown 或精确章节；
- 使用显式 `task_id` 记录同一任务的实际文档读取链路。

项目同时已经具备数据源、远端数据库清单、项目数据库关联和查询策略的管理模型，但这些数据尚未进入 MCP 执行链路。ClickHouse 也只存在于类型、数据库约束和前端选项中，尚不具备连接测试、数据库同步、Schema 探索或查询执行能力。

本设计的目标是把 Context Router 扩展为一个本地的“项目文档上下文 + 项目数据库上下文”路由器，使 Agent 在同一个 MCP Server 中：

1. 通过现有 `prepare_task_context` 建立项目任务上下文；
2. 从 prepare 返回中知道当前项目允许访问哪些只读数据库；
3. 以渐进披露方式探索数据库对象；
4. 在服务端策略约束下执行单条只读查询；
5. 无需知道或传递 Host、端口、账号、密码、DSN 和内部数据源 ID；
6. 不因某个业务数据库离线而影响原有文档 MCP 能力。

本项目继续面向单机、单用户的 Codex 和 Antigravity。本轮不建设 OAuth、OIDC、RBAC、Scope 或远程多租户能力，但必须保留防止 Agent 误写数据、跨库访问和无界查询的安全护栏。

## 2. 与既有设计的关系

本文是以下已落地设计的增量设计：

- `2026-07-19-mcp-only-context-router-design.md`
- `2026-07-20-prepare-task-context-mcp-design.md`
- `2026-07-20-read-context-document-mcp-design.md`

本文只覆盖旧设计中的两项约束：

1. “AI 只感知两个 MCP 工具”调整为“AI 感知四个稳定 MCP 工具”。
2. `prepare_task_context` 在原文档树之外，增加当前项目可查询数据库的精简摘要。

以下既有约束继续有效：

- MCP 使用无状态 Streamable HTTP；
- 一个新任务先调用一次 `prepare_task_context`；
- 后续调用显式携带当前任务的 `task_id`；
- 项目继续按 `cwd` 最长目录前缀匹配；
- `task_id` 由 PostgreSQL 生成，Agent 不传顺序号；
- 文档树和正文仍使用当前内存缓存，不写入数据库；
- Web 负责管理与观察，Agent 只使用 MCP；
- Context Router 不自动修改 Codex 或 Antigravity 配置；
- 服务继续只通过当前仓库的 Docker Compose 运行和验证。

如果本文与旧文档在数据库工具数量、prepare 返回结构或项目数据库访问规则上冲突，以本文为准；其他文档能力不受影响。

## 3. 已确认的核心决策

### 3.1 一个 MCP Server，四个稳定工具

最终工具集固定为：

```text
prepare_task_context
read_context_document
search_database_objects
execute_database_query
```

数据源增删、停用或配置更新都不能改变 `tools/list`。不按数据源生成 `execute_sql_prod`，也不为 ClickHouse 注册一组专用工具。

### 3.2 `task_id` 是项目上下文句柄，不是鉴权凭证

数据库调用统一沿以下链路解析：

```text
task_id
  -> mcp_tasks.project_key
  -> ProjectRegistry 当前项目快照
  -> project_databases 当前启用关联
  -> 项目内唯一 mcp_alias
  -> data_source_databases 当前数据库
  -> data_sources 当前连接配置
  -> 当前查询策略
```

`task_id` 用于避免多个窗口、项目和数据库串线，不用于防止本机其他进程猜测编号。因此后端端口必须继续只绑定回环地址。未来若开放局域网或公网，需要重新设计认证和不可猜测的任务令牌。

### 3.3 数据库工具只接受项目内短别名

Agent 只传 `task_id` 和 prepare 返回的 `mcp_alias`。数据库 MCP 参数中禁止出现：

- `project_id`
- `data_source_id`
- `database_id`
- Host 或端口
- 用户名或密码
- DSN
- 客户端自定义 `readonly`、timeout、max rows 或数据库 settings

短别名提高可读性和 Token 效率，同时由服务端验证其是否属于当前任务项目。

### 3.4 第一版 MCP 永远只读

第一版数据库 MCP 不提供写入能力：

- 只有 `readonly=true` 的项目数据库关联会出现在 prepare 摘要中；
- `readonly=false` 的关联仍可保留在管理模型中，但不向 MCP 暴露；
- 不提供人工确认后写入、事务会话、DDL、DML 或自定义写工具；
- 数据库账号最小权限仍是最终安全边界。

“不需要鉴权”不等于“不需要查询安全”。只读护栏用于防止 Agent 误操作、提示注入、跨库访问和资源失控。

### 3.5 prepare 不连接业务数据库

`prepare_task_context` 只读取当前项目数据库关联的控制面记录，不 ping、不创建连接池、不查询远端 Schema。某个业务数据库离线不能拖慢或阻断文档上下文准备。

### 3.6 复用设计，不直接复制两个外部项目代码

- 从 DBHub 继承统一 Connector、lazy manager、两个通用数据库工具、渐进 Schema、只读纵深防御和 Token 友好结果格式的设计。
- 从 MCP Toolbox 继承 Source/Tool 分离、按能力注册、先建立并验证新连接再切换的设计。
- 不复制 DBHub 的 TypeScript Connector、TOML/DSN 配置、按 Source 动态工具名或多语句支持。
- 不复制 MCP Toolbox 的 Go 代码、认证、Toolset、Prompt、Embedding、重型遥测、海量预置 Tool 和自维护 MCP 协议。

## 4. 当前可复用资产与能力缺口

### 4.1 已有能力

目标项目已经具备：

- `DataSourceRecord`：物理数据源及 `config_version`；
- `DataSourceDatabaseRecord`：远端数据库、Schema 或文件清单；
- `ProjectDatabaseLinkRecord`：项目与数据库关联；
- `readonly`、`allowed_schemas`、`max_rows`、`max_result_bytes`、`query_timeout_ms`；
- 数据源列表、编辑、密码过滤和按需 reveal；
- MySQL/MariaDB/PostgreSQL 数据库清单同步；
- `task_id -> project_key -> ProjectSnapshot` 的项目隔离链路；
- FastMCP 无状态 HTTP Server；
- Codex/Antigravity 配置模板和真实 MCP 自检；
- Docker Compose 启动、测试、lint、build 和 migration 规范。

### 4.2 当前缺口

当前尚未实现：

- 运行时数据库 Connector Protocol 和 Registry；
- 业务数据库连接生命周期管理；
- 项目数据库 MCP 别名；
- ClickHouse Python 驱动和连接配置校验；
- ClickHouse 数据库同步；
- 跨数据库统一 Schema 搜索；
- 只读 SQL AST 分类和数据库级兜底；
- 行数、最终 JSON 字节数和查询超时的执行层限制；
- Token 友好的结构化查询结果；
- 数据库 MCP 工具和调用记录；
- UI 对“仅可配置 / 可同步 / 可查询”的真实能力展示。

## 5. 本轮范围与非目标

### 5.1 本轮范围

本轮设计覆盖：

1. 项目数据库 `mcp_alias` 数据模型与兼容迁移；
2. 窄接口 Database Connector、Registry、Resolver 和 Manager；
3. ClickHouse 连接、ping、数据库同步、对象搜索和只读查询；
4. PostgreSQL、MySQL、MariaDB 的统一运行时接入；
5. `search_database_objects` 和 `execute_database_query`；
6. prepare 返回数据库精简摘要；
7. SQL 单语句、只读、Schema 作用域和危险能力限制；
8. 结果行数、字节数、超时、扫描量和并发限制；
9. 数据库调用元数据记录；
10. 数据源能力状态、连接测试和 ClickHouse 配置 UI；
11. Fake Connector 单元测试和真实 ClickHouse Docker 集成测试；
12. Codex/Antigravity 的 MCP 端到端验证。

### 5.2 明确非目标

第一版不实现：

- OAuth、OIDC、Scope、RBAC 和远程多租户；
- 写 SQL、DDL、DML 和事务会话；
- 动态 MCP Tool、Toolset、Prompt 或 Embedding；
- 任意自定义 SQL Tool DSL；
- 数据库结果 SSE、MCP streaming 或 continuation token；
- 自动分页；
- ClickHouse mutation、复制、集群管理和 DBA 运维工具；
- SSH Tunnel、ProxyJump、RDS IAM Token；
- 多进程或多副本 Connector 缓存同步；
- 持久化完整查询结果；
- 默认持久化完整 SQL 文本；
- Oracle 查询 Connector；
- 向量检索或大模型生成 Schema 摘要；
- 将 Router 自身的 PostgreSQL 元数据存储改成 SQLite。

## 6. 数据库范围与能力矩阵

数据库类型需要区分“允许保存配置”和“当前真正可运行”，不能继续用一个枚举暗示所有能力已经完成。

| Engine | 当前配置 | 当前同步 | 本设计查询目标 | 说明 |
| --- | --- | --- | --- | --- |
| PostgreSQL | 是 | 是 | V1 | 复用 psycopg，增加 Catalog 和只读执行 |
| MySQL | 是 | 是 | V1 | 复用 PyMySQL |
| MariaDB | 是 | 是 | V1 | 复用 MySQL Adapter，保留方言标识 |
| ClickHouse | 是 | 否 | V1 | 新增官方 Python Client 和完整只读链路 |
| SQLite | 是 | 手工 | 后续可选 | 使用标准库，需先解决宿主机/容器文件路径映射 |
| SQL Server | 是 | 手工 | 后续可选 | 需要额外 ODBC/容器依赖，按真实需求实施 |
| Oracle | 是 | 手工 | 非目标 | 保留历史配置兼容，不声明 MCP 查询支持 |

最终若需要覆盖 DBHub 原有范围，可在 V1 稳定后增加 SQLite 和 SQL Server；不因为页面已有类型就一次性实现所有 Connector。

能力状态统一表达为：

```text
configurable
discoverable
searchable
queryable
```

前端必须基于后端返回的能力状态决定是否显示“同步数据库”“测试连接”和“MCP 可查询”，不能继续仅靠静态 Engine 数组推断。

## 7. 总体架构

```text
Codex / Antigravity
  -> POST /mcp
  -> prepare_task_context(task, cwd, agent_name?)
       -> ProjectRegistry：cwd 最长前缀匹配
       -> TaskRepository：创建 task_id
       -> DataSourceRepository：读取当前项目可查询数据库摘要
       -> 返回 documents + databases

  -> search_database_objects(task_id, database, ...)
       -> DatabaseAccessService：task/project/alias/状态解析
       -> QueryPolicyService：有效策略与作用域
       -> ConnectorManager：lazy lease
       -> Connector.search_objects()
       -> DatabaseResultFormatter

  -> execute_database_query(task_id, database, sql)
       -> DatabaseAccessService
       -> SqlSafetyPolicy：AST fail-closed
       -> ConnectorManager：lazy lease
       -> Connector.execute_query()
       -> 行数/字节/超时限制
       -> DatabaseResultFormatter
```

控制面和执行面必须分离：

- Repository 只读写配置、关联和调用元数据；
- DatabaseAccessService 只负责项目作用域和策略解析；
- Connector 不知道 project、task 或 MCP；
- MCP handler 只做参数接收、调用 Service 和错误转换；
- 前端不直接调用 Connector。

## 8. 领域术语

| 术语 | 含义 |
| --- | --- |
| Data Source | 一个物理数据库服务或本地数据库文件配置 |
| Source Database | Data Source 下发现或手工维护的具体数据库/Schema/文件 |
| Project Database Link | 一个项目对某个 Source Database 的当前关联和查询策略 |
| MCP Alias | 项目内唯一、稳定、适合 Agent 传递的数据库短名称 |
| Query Policy | readonly、Schema 范围、行数、结果字节和超时的当前有效策略 |
| Connector | 面向某个 Engine 和具体数据库的执行适配器 |
| Connector Lease | Manager 在一次搜索或查询期间提供的活动连接租约 |

## 9. 数据模型与迁移

### 9.1 项目数据库 MCP 别名

现有 `alias` 是人类可读显示名，可以为空、包含中文或重复，不适合作为稳定机器选择器。新增独立字段：

```sql
ALTER TABLE project_databases
    ADD COLUMN mcp_alias VARCHAR(64);

ALTER TABLE project_databases
    ADD CONSTRAINT ck_project_databases_mcp_alias
    CHECK (
        mcp_alias IS NULL
        OR mcp_alias ~ '^[a-z][a-z0-9_-]{0,63}$'
    );

CREATE UNIQUE INDEX uq_project_databases_project_mcp_alias
    ON project_databases(project_id, lower(mcp_alias))
    WHERE mcp_alias IS NOT NULL;
```

迁移文件新增为当前 head 之后的新 migration，不修改历史 `20260722_0004`。

兼容规则：

- `mcp_alias` 数据库层暂时允许空，保证旧代码回滚后仍能创建 Link；
- MCP 只暴露非空且通过校验的别名；
- 新建关联时服务端自动生成别名，页面允许用户修改；
- 自动生成优先使用规范化后的当前 alias、display name 或 remote name；
- 无法生成 ASCII slug 时使用 `db_<link-id 前 8 位>`；
- 项目内冲突时追加稳定短后缀；
- 不自动修改现有的人类显示 alias；
- migration upgrade/downgrade 必须保持所有已有连接、密码 JSON、数据库 ID、Link 和策略不丢失。

### 9.2 数据库调用元数据

为了让 Tasks 页面继续观察 Agent 的客观调用链，新增数据库调用表，只保存元数据，不保存结果集、密码、DSN 或完整 SQL：

```sql
CREATE TABLE mcp_database_calls (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    task_id BIGINT NOT NULL REFERENCES mcp_tasks(id) ON DELETE CASCADE,
    operation VARCHAR(32) NOT NULL,
    database_alias VARCHAR(64) NOT NULL,
    engine VARCHAR(32) NOT NULL,
    object_type VARCHAR(32),
    statement_type VARCHAR(32),
    sql_sha256 VARCHAR(64),
    status VARCHAR(32) NOT NULL,
    duration_ms INTEGER,
    returned_count INTEGER,
    result_bytes INTEGER,
    truncated BOOLEAN,
    error_code VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_mcp_database_calls_task_id_id
    ON mcp_database_calls(task_id, id);
```

设计约束：

- `operation` 只允许 `search_objects` 或 `execute_query`；
- SQL 只保存 SHA-256 和根语句类型，不默认保存原文；
- 不保存返回行和 Schema 详情；
- 错误只保存稳定错误码，不保存可能带凭据的原始驱动异常；
- 页面按 `created_at` 和调用 ID 与文档读取记录组合展示；
- 调用记录失败不能导致同一只读 SQL被隐式重试。

### 9.3 Connection Config

`data_sources.connection_config` 已经是 JSON，不需要为 ClickHouse TLS 等字段修改表结构。运行时必须按 Engine 使用独立 Pydantic 模型解析，不再直接消费无约束的 `dict[str, Any]`。

## 10. 模块与文件职责

计划新增：

```text
backend/src/context_router/
├── database/
│   ├── models.py
│   │   # ConnectorSpec、Capabilities、Policy、Search/Query Result
│   ├── protocol.py
│   │   # 窄 DatabaseConnector Protocol
│   ├── registry.py
│   │   # engine -> ConnectorFactory 与能力查询
│   ├── manager.py
│   │   # lazy、single-flight、lease、retire、invalidate、close_all
│   ├── policy.py
│   │   # SQL AST、Schema 作用域和有效限制
│   ├── result.py
│   │   # JSON 类型归一化、行数和字节预算
│   └── connectors/
│       ├── postgresql.py
│       ├── mysql.py
│       └── clickhouse.py
├── services/
│   ├── database_access.py
│   │   # task_id -> project -> mcp_alias -> 当前连接与策略
│   ├── database_catalog.py
│   │   # search_database_objects 业务编排
│   └── database_query.py
│       # execute_database_query 业务编排和调用记录
├── schemas/
│   └── database_tools.py
│       # MCP 输入输出 Pydantic 模型
└── repositories/
    └── database_call_repository.py
        # 调用元数据写入和历史读取
```

计划调整：

```text
backend/src/context_router/mcp_server.py
backend/src/context_router/main.py
backend/src/context_router/config.py
backend/src/context_router/services/context_preparation.py
backend/src/context_router/services/database_discovery.py
backend/src/context_router/services/mcp_integration.py
backend/src/context_router/repositories/data_source_repository.py
backend/src/context_router/schemas/context.py
backend/src/context_router/schemas/data_sources.py
backend/src/context_router/api/data_sources.py
backend/pyproject.toml
backend/uv.lock
frontend/components/data-source-dashboard.tsx
frontend/components/mcp-integration-panel.tsx
frontend/lib/types.ts
frontend/lib/api.ts
docker-compose.yml
```

现有 `database_discovery.py` 最终降为 Registry 的薄入口，或由 Engine Connector 的 `discover_databases()` 完全替代，避免数据库连接逻辑继续散落在 Service。

## 11. Connector Protocol 与能力注册

第一版采用窄接口：

```python
class DatabaseConnector(Protocol):
    @property
    def engine(self) -> str: ...

    @property
    def capabilities(self) -> ConnectorCapabilities: ...

    def ping(self) -> None: ...

    def discover_databases(self) -> list[DiscoveredDatabase]: ...

    def search_objects(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
    ) -> SearchObjectsResult: ...

    def execute_query(
        self,
        sql: str,
        policy: EffectiveQueryPolicy,
    ) -> QueryResult: ...

    def close(self) -> None: ...
```

能力模型至少包含：

```text
discover_databases
search_schemas
search_tables
search_views
search_columns
search_indexes
execute_readonly_query
```

Registry 规则：

- 一个 Engine 只能注册一个 Factory；
- 重复注册在启动测试中失败；
- Engine 未注册时返回 `engine_not_supported`；
- UI 能力状态来自 Registry，不硬编码为“全部可查询”；
- Connector 初始化失败不阻止 Context Router 启动；
- Catalog 查询使用 Connector 内部固定、参数化 SQL。

Connector 第一版保持同步接口，与当前 Repository 和 FastMCP Tool 风格一致。所有阻塞数据库 I/O 必须运行在线程池，不得直接阻塞 FastAPI event loop；如果 MCP SDK 当前路径不能保证这一点，Tool Service 显式使用 `anyio.to_thread.run_sync`。并发测试必须证明长查询不会阻塞 `/health` 和文档 MCP。

## 12. DatabaseAccessService 与项目隔离

`DatabaseAccessService.resolve(task_id, mcp_alias)` 是数据库调用唯一入口。

解析顺序：

1. `TaskRepository.get_task(task_id)`；
2. 使用 `project_key` 调用 `ProjectRegistry.get_snapshot_by_project_key()`；
3. 使用一次 Repository JOIN 查询当前项目、Link、Database 和 Source；
4. 按大小写无关方式精确匹配 `mcp_alias`；
5. 校验 Link enabled；
6. 校验 Link readonly；
7. 校验 Source enabled；
8. 校验 Database available；
9. 校验 Engine 已注册且支持目标操作；
10. 生成不可变 `ResolvedDatabaseContext` 和 `EffectiveQueryPolicy`。

Repository 应增加类似以下一次性解析方法，避免调用方先列出全部 Link 再做 N+1 查询和分散状态检查：

```python
def get_project_database_by_alias(
    self,
    *,
    project_id: str,
    mcp_alias: str,
) -> ResolvedProjectDatabase: ...
```

一致性语义：

- 每次数据库调用读取当前关联和当前策略，不冻结 prepare 时的配置；
- Link、Source 停用或 Database unavailable 后，已有 task 立即不可再查询；
- 项目路径改变导致 `project_key` 变化时，旧 task 与文档读取一致地失效，Agent 重新 prepare；
- 项目改名但 AGENTS 路径不变，不影响旧 task；
- 找不到 alias 时统一返回 `database_not_found`，不透露其他项目是否存在同名数据库。

## 13. ConnectorManager 生命周期

### 13.1 缓存键

连接不能只按 Source 缓存，因为 PostgreSQL/MySQL 连接通常绑定具体数据库。缓存键使用：

```text
(
  data_source_id,
  data_source.config_version,
  database_id,
  database.updated_at
)
```

或由以上非敏感字段与规范化连接规格生成的等价指纹。项目 alias、purpose 和查询限制变化不重建连接。

### 13.2 强制行为

Manager 必须满足：

- 应用启动时业务数据库连接数为 0；
- 首次调用才创建 Connector；
- 同一个 key 并发初始化只执行一次；
- 初始化失败不缓存失败对象；
- 新 Connector 必须 ping 成功后才能发布；
- config version 改变时不能继续使用旧配置连接；
- 旧 Connector 进入 retiring，活动 lease 归零后关闭；
- Manager 的锁只保护状态，不覆盖远端查询过程；
- 数据源更新、停用或删除时支持 `invalidate_source()`；
- FastAPI lifespan 退出时执行 `close_all()`；
- `close()`、invalidate 和 shutdown 必须幂等；
- 第一版最多缓存 16 个 Connector，每个 Source 默认最多 4 个并发查询；
- 超出缓存上限时按 LRU 回收无活动 lease 的 Connector；
- 不记录密码、完整 DSN 或带凭据的连接异常。

第一版明确以当前单后端进程、单 Uvicorn worker 为边界，不设计多进程缓存失效广播。

### 13.3 更新和回滚

配置变化时采用 make-before-break：

1. 旧 lease 继续完成当前只读查询；
2. 新请求发现新 `config_version`；
3. Manager 创建并 ping 新 Connector；
4. 成功后发布新 Connector，旧 Connector retiring；
5. 新连接失败时返回 `connection_failed`，不能静默回退旧凭据；
6. 旧 Connector 的活动 lease 归零后关闭。

不回退旧配置是为了避免用户修改密码、Host 或停用连接后，Agent 仍然访问已经撤销的目标。

## 14. MCP Server 总体契约

MCP Server instructions 调整为：

- 新任务调用一次 `prepare_task_context`；
- 保存 `task_id`；
- 文档按现有协议调用 `read_context_document`；
- 数据库任务先查看 prepare 返回的数据库摘要；
- 不确定表结构时先调用 `search_database_objects`；
- 只执行必要的只读查询；
- 不猜测数据库别名，不复用其他任务的 task_id。

四个 Tool 名称和参数契约在 V1 后保持稳定。连接配置变化不要求重启 MCP Server。

## 15. `prepare_task_context` 数据库扩展

原有字段保持不变，新增 `databases`：

```json
{
  "task_id": 128,
  "project": {
    "project_id": "9e3c...",
    "name": "订单服务",
    "node_count": 12
  },
  "documents": {
    "document_id": "a82f...",
    "path": "AGENTS.md",
    "children": []
  },
  "databases": [
    {
      "database": "analytics",
      "engine": "clickhouse",
      "name": "events",
      "purpose": "行为日志分析",
      "readonly": true,
      "capabilities": ["search_objects", "execute_query"]
    }
  ]
}
```

返回规则：

- `database` 就是项目内唯一 `mcp_alias`；
- 只返回 Link enabled、Link readonly、Source enabled、Database available 且 Engine queryable 的关联；
- 按 `database` 排序，保持稳定输出；
- 不返回 Host、端口、用户名、密码、Source ID、Database ID 或 connection config；
- 不执行 ping，不保证远端此刻在线；
- 没有关联时返回 `databases: []`，prepare 仍成功；
- 数据库摘要读取失败时不能破坏文档 prepare，返回空数组并附加精简 warning；
- `readonly=false` 关联不返回，也不静默改成只读。

## 16. `search_database_objects` 工具契约

### 16.1 输入

```json
{
  "task_id": 128,
  "database": "analytics",
  "object_type": "table",
  "pattern": "event_*",
  "detail": "names",
  "schema": null,
  "table": null,
  "limit": 100
}
```

字段：

| 字段 | 必填 | 规则 |
| --- | --- | --- |
| `task_id` | 是 | 正整数，来自当前任务 prepare |
| `database` | 是 | prepare 返回的 `mcp_alias` |
| `object_type` | 是 | `schema/table/view/column/index` |
| `pattern` | 否 | 普通 glob，默认 `*`，支持 `*` 和 `?` |
| `detail` | 否 | `names/summary/full`，默认 `names` |
| `schema` | 否 | 限定 Schema；必须通过项目策略校验 |
| `table` | 否 | column/index 搜索时可限定表 |
| `limit` | 否 | 默认 100，最小 1，最大受服务端限制 |

`pattern` 采用普通 glob，不直接接受数据库 LIKE 表达式。Service 将 glob 转换为转义后的数据库条件，并始终参数绑定，避免不同数据库的 `%`、`_` 转义差异泄露给 Agent。

### 16.2 Detail 语义

- `names`：只返回对象名、类型、Schema/Database；
- `summary`：增加列数、Engine、估算行数/大小和 comment 等廉价元数据；
- `full`：增加完整列定义、键、默认表达式和索引等结构；
- 不使用 `COUNT(*)` 扫描业务表获取行数；没有廉价统计值时返回 `null`；
- `full` 的服务端最大对象数为 20；
- `summary` 最大对象数为 100；
- `names` 最大对象数为 500；
- 所有 Detail 都受最终响应字节上限约束。

### 16.3 成功返回

```json
{
  "task_id": 128,
  "database": "analytics",
  "engine": "clickhouse",
  "object_type": "table",
  "detail": "names",
  "objects": [
    {
      "name": "event_daily",
      "schema": "events",
      "kind": "table"
    }
  ],
  "returned_count": 1,
  "truncated": false,
  "truncation_reason": null,
  "elapsed_ms": 11,
  "result_bytes": 148
}
```

## 17. `execute_database_query` 工具契约

### 17.1 输入

```json
{
  "task_id": 128,
  "database": "analytics",
  "sql": "SELECT day, count() AS events FROM event_daily GROUP BY day ORDER BY day DESC LIMIT 7"
}
```

第一版不接受参数绑定 Map、客户端 timeout、max rows、readonly、数据库 settings 或分页参数。所有限制来自服务端当前策略。

### 17.2 成功返回

```json
{
  "task_id": 128,
  "database": "analytics",
  "engine": "clickhouse",
  "columns": [
    {"name": "day", "type": "Date"},
    {"name": "events", "type": "UInt64"}
  ],
  "rows": [
    ["2026-07-21", "1382"],
    ["2026-07-22", "1640"]
  ],
  "returned_rows": 2,
  "truncated": false,
  "truncation_reason": null,
  "elapsed_ms": 18,
  "result_bytes": 198
}
```

返回规则：

- `returned_rows` 是实际返回给 Agent 的行数，不表示远端总行数；
- 列名和类型只输出一次，rows 使用二维数组避免每行重复 JSON key；
- 行数或字节达到限制仍是成功响应，但 `truncated=true`；
- timeout、解析失败、连接失败不返回部分结果；
- 不回显 SQL、Host、DSN、用户信息和底层驱动堆栈；
- 单个值或列元数据本身超过预算时返回稳定错误，不产生超大 MCP 响应。

## 18. SQL 只读与作用域策略

查询执行采用三层防御。

### 18.1 第一层：SQL AST fail-closed

使用 SQLGlot，并显式指定 Engine 对应方言。要求：

- 解析结果必须恰好一条语句；
- 允许尾部一个普通分号；
- 允许 `SELECT`、最终落到 SELECT 的 `WITH`、`SHOW`、`DESCRIBE/DESC`、`EXPLAIN`、`EXISTS`；
- 解析失败直接返回 `query_rejected`，不把原 SQL 交给数据库尝试；
- 禁止 INSERT、UPDATE、DELETE、MERGE、CREATE、ALTER、DROP、TRUNCATE、RENAME；
- 禁止 ATTACH、DETACH、OPTIMIZE、SYSTEM、KILL、BACKUP、RESTORE；
- 禁止 SET、USE、事务控制、GRANT、REVOKE、CALL；
- 禁止 `INTO OUTFILE`、服务端文件输出和任意自定义 FORMAT；
- 禁止 SQL 内 `SETTINGS` 覆盖服务端注入限制；
- 前置注释、混合大小写、CTE、嵌套子查询和 quoted identifier 不能绕过检查。

SQLGlot 未覆盖的合法数据库语法会被拒绝，这是有意的 fail-closed 取舍。错误应提示 Agent 简化查询，而不是自动降级到字符串前缀判断。

### 18.2 第二层：数据库与 Schema 作用域

遍历 AST 中的物理表引用：

- 未限定数据库的表解释为当前项目关联数据库；
- 显式数据库名只能等于当前绑定数据库；
- CTE 名和子查询别名不当作物理表；
- `allowed_schemas=[]` 表示当前数据库内全部非系统、当前账号可见 Schema；
- 非空 `allowed_schemas` 表示严格白名单；
- PostgreSQL 在只读事务中设置受控 `search_path`；
- MySQL/MariaDB 只能访问当前连接绑定数据库；
- ClickHouse 不能查询其他 database；
- 通用执行工具默认不能查询 system catalog，Catalog 只由服务端固定 SQL访问。

第一版禁止所有 FROM/JOIN table function。尤其 ClickHouse 禁止 `url`、`file`、`remote`、`s3`、`hdfs`、`mysql`、`postgresql`、`jdbc`、`odbc` 等外部访问能力，防止 readonly 查询造成 SSRF、本地文件读取或绕过当前数据源边界。

### 18.3 第三层：数据库级兜底

- PostgreSQL：`BEGIN READ ONLY`，并设置 `statement_timeout`；
- MySQL/MariaDB：只读事务和驱动超时；
- ClickHouse：每次查询强制 `readonly=1` 及资源 settings；
- 所有 Engine：使用数据库最小权限只读账号；
- Connector 不允许 SQL 覆盖服务端注入的限制。

AST 分类属于 Agent 误操作防护，不能替代数据库权限。

## 19. 查询预算与 Token 限制

当前项目关联允许的最大值高于适合 MCP 的范围，因此有效限制为：

```text
effective_value = min(project_database_value, MCP service hard cap)
```

V1 默认与硬上限：

| 项目策略默认 | MCP 硬上限 |
| --- | --- |
| `max_rows=1000` | 5000 |
| `max_result_bytes=2_000_000` | 4_000_000 |
| `query_timeout_ms=15_000` | 30_000 |

Schema 搜索额外限制：

- names 最大 500 个对象；
- summary 最大 100 个对象；
- full 最大 20 个对象；
- Schema 工具最终响应最大 1 MB。

实现规则：

- 远端读取最多 `max_rows + 1`，用于准确判断截断；
- 最终只返回 `max_rows`；
- 使用流式 cursor/rows stream，不先把全部结果物化到内存；
- 逐行归一化并计算最终 compact JSON 的 UTF-8 字节数；
- 添加下一行会越界时不添加该行，设置 `truncated=true`；
- `truncation_reason` 为 `rows`、`bytes` 或按固定优先级选择；
- 单个字段超过预算时返回 `result_cell_too_large`；
- 列元数据超过预算时返回 `result_metadata_too_large`；
- 不能使用 Python `sys.getsizeof` 代替 JSON UTF-8 大小；
- 服务端查询限制用于防止驱动在应用截断前下载或物化超大结果。

## 20. 统一类型序列化

结果格式化必须递归处理：

- JavaScript 安全范围内整数输出 JSON number；
- 超出安全范围的 Int/UInt 输出字符串；
- Decimal 输出字符串；
- Date、DateTime、DateTime64 输出 ISO 8601；
- UUID、IPv4、IPv6 输出字符串；
- bytes 统一输出 Base64；
- Array、Tuple、Map、Nested 递归应用相同规则；
- NaN 和 Infinity 转字符串或 null，必须固定一种实现并保持合法 JSON；
- Nullable 保持 null；
- 重复列名通过 columns 数组位置区分，不转换成覆盖 key 的 Map。

Formatter 必须在 MCP、REST 调试接口和调用历史预览之间复用同一实现。

## 21. ClickHouse 专项设计

### 21.1 驱动

使用官方 `clickhouse-connect>=1,<2` HTTP Client，具体版本由 `uv.lock` 固定。第一版使用同步 Client，与 Connector Protocol 保持一致；阻塞 I/O 在线程池执行。

不移植 MCP Toolbox 的 Go `database/sql` 实现，也不增加 SQLAlchemy ORM。

### 21.2 配置模型

ClickHouse 配置至少包含：

```text
host
port
username
password
secure
verify
bootstrap_database
connect_timeout_seconds
send_receive_timeout_seconds
```

规则：

- HTTP 默认端口 8123；
- HTTPS/Cloud 常用 8443，但端口仍以用户配置为准；
- `verify` 默认 true；
- `bootstrap_database` 默认 `default`，只用于建立管理连接；
- 目标业务数据库始终来自 `data_source_databases.remote_name`；
- 不在异常或日志中打印 password；
- 自定义 CA 文件不属于第一版，使用系统 CA 或显式关闭 verify；
- 后端在 Docker 中访问宿主机 ClickHouse 时使用 `host.docker.internal`；
- ClickHouse 作为 Compose 服务时使用服务名；
- 不自动把用户填写的 `127.0.0.1` 静默改写成其他 Host。

### 21.3 数据库同步

使用参数固定的 Catalog 查询：

```sql
SELECT name
FROM system.databases
ORDER BY name
```

同步规则继续复用现有原子行为：

- 完整 discover 成功后才写入本地数据库清单；
- 保留既有数据库 ID 和项目关联；
- 新发现数据库新增；
- 远端不再可见的数据库标记 unavailable，不直接删除；
- discover 失败不把旧数据库全部标记 unavailable；
- `system`、`information_schema`、`INFORMATION_SCHEMA` 标记为系统数据库。

### 21.4 Schema 探索

使用参数化系统表查询：

- `system.databases`
- `system.tables`
- `system.columns`
- `system.data_skipping_indices`

`system.tables` 用于 table/view kind、Engine、估算 rows/bytes、comment、sorting key、primary key、partition key；`system.columns` 用于类型、Nullable、默认表达式、comment 和键标记。

不使用拼接标识符的 `SHOW TABLES FROM <database>`。数据库名、表名、glob 转换结果和 limit 都必须通过参数或服务端固定常量进入查询。

### 21.5 查询 settings

每次普通查询至少强制：

```text
readonly=1
max_execution_time=<effective timeout>
max_result_rows=<effective rows + 1>
result_overflow_mode=break
max_result_bytes=<effective bytes>
max_threads=4
max_rows_to_read=10_000_000
max_bytes_to_read=1_000_000_000
max_memory_usage=1_000_000_000
```

这些值是 V1 本地默认值，后续可以从 Settings 下调；Agent 和 SQL 不能放宽。

每次查询生成唯一 `query_id`，便于 ClickHouse 侧定位调用。V1 依赖 ClickHouse `max_execution_time` 和 HTTP 收发超时终止长查询；应用层主动发送 `KILL QUERY` 属于后续增强，当前不把 `query_id` 等同于已实现主动取消。

## 22. PostgreSQL、MySQL 和 MariaDB

### 22.1 PostgreSQL

- 复用 psycopg；
- 数据库连接绑定 `remote_name`；
- Catalog 使用 `pg_catalog` 和 `information_schema` 批量查询；
- 普通查询使用只读事务；
- 设置 `statement_timeout`；
- 非空 `allowed_schemas` 设置受控 `search_path` 并校验显式引用；
- row estimate 使用统计信息，不 fallback `COUNT(*)`。

### 22.2 MySQL/MariaDB

- 复用 PyMySQL；
- MariaDB 共享 Adapter 主体，但保留 Engine/dialect 区分；
- 数据库连接绑定 `remote_name`；
- Catalog 使用 `information_schema`；
- 使用只读事务、read timeout 和 streaming cursor；
- 数据库账号最小权限用于兜底 MySQL DDL 隐式提交等差异；
- 不允许跨 database 引用。

### 22.3 后续 Connector

- SQLite：优先使用标准库，但必须先定义宿主机绝对路径到 `/workspace` 只读挂载的安全映射，并启用 `PRAGMA query_only`；
- SQL Server：需新增驱动和容器系统依赖，使用事务回滚或只读账号兜底；
- Oracle：本设计不安排实现。

## 23. 数据源 API 与前端

### 23.1 Engine 能力接口

后端增加只读能力接口，返回每个 Engine 的：

```json
{
  "engine": "clickhouse",
  "configurable": true,
  "discoverable": true,
  "searchable": true,
  "queryable": true
}
```

前端以该接口决定操作状态。未实现 Connector 的 Engine 可以继续展示历史配置，但必须标记“仅配置管理，暂不支持 MCP 查询”。

### 23.2 连接测试

增加：

```text
POST /api/data-sources/{data_source_id}/test
```

返回 Engine、状态、耗时和短错误码；不返回服务器版本以外的敏感信息。测试使用当前完整 Connection Config，并遵守连接超时。测试不进入 Connector 长期缓存，或成功后由 Manager 按正常 key 接管，具体实现必须保持唯一生命周期所有者。

### 23.3 ClickHouse 编辑

前端补充：

- secure；
- verify；
- bootstrap database；
- connect timeout；
- Docker Host 提示；
- 测试连接；
- 同步全部数据库。

密码继续遵守：

- 列表 API 不返回；
- 编辑时密码为空保留旧值；
- 仅点击眼睛时通过 no-store API读取；
- MCP、连接测试错误和日志都不返回密码。

### 23.4 项目数据库别名

项目管理数据库弹窗展示并可编辑 `mcp_alias`：

- 前端实时校验格式；
- 后端执行最终校验和项目内唯一性；
- 冲突返回明确错误；
- purpose 应说明该数据库适合什么任务；
- readonly=false 时提示“不会暴露给 MCP”。

## 24. 数据库调用记录与 Tasks 页面

数据库调用记录只保存客观事实：

- tool operation；
- database alias 和 Engine 快照；
- object type 或 statement type；
- SQL hash；
- 成功、拒绝、超时或失败状态；
- duration、returned count、result bytes、truncated；
- 稳定 error code。

默认不保存：

- 连接参数和密码；
- 完整 SQL；
- SQL 参数值；
- Schema 搜索完整结果；
- 查询结果集；
- Agent 主观解释或任务成功率。

Tasks 详情未来可按时间展示：

```text
prepare_task_context
read_context_document
search_database_objects analytics / table / names
execute_database_query analytics / SELECT / 120 rows / truncated=false
```

数据库调用历史页面不是核心查询能力的前置阻塞项，但表结构和记录 Service 应在 V1 中完成，避免后续无法还原客观调用链。

## 25. 错误模型与敏感信息

至少定义以下稳定错误码：

| code | 含义 |
| --- | --- |
| `task_not_found` | task_id 不存在 |
| `project_unavailable` | 任务绑定项目当前不可用 |
| `database_not_found` | 当前项目没有该 MCP alias |
| `database_not_available` | Link/Source/Database 当前停用或不可用 |
| `engine_not_supported` | Engine 没有目标能力 |
| `connection_failed` | 无法建立或验证连接 |
| `database_auth_failed` | 数据库认证失败 |
| `query_rejected` | SQL 不符合只读或作用域策略 |
| `query_timeout` | 查询超时 |
| `query_cancelled` | 查询被取消 |
| `catalog_query_failed` | 固定 Catalog 查询失败 |
| `result_cell_too_large` | 单个值超过结果预算 |
| `result_metadata_too_large` | 列元数据超过结果预算 |
| `query_failed` | 已清洗的普通数据库错误 |

错误原则：

- MCP 使用 ToolError 或等价 isError 结构；
- 对 Agent 返回短、可操作信息；
- 不返回 Python traceback；
- 不返回底层驱动完整异常文本；
- 不返回 Host、DSN、用户名、密码和 SQL 参数；
- 服务端日志也必须经过凭据清洗；
- 每次错误可带内部 correlation ID，便于本机日志定位。

## 26. 本地安全边界

不建设身份认证的前提是服务永远保持本地边界：

- Docker Compose 后端继续映射 `127.0.0.1:49173:8000`；
- 前端也建议绑定回环地址；
- CORS 从 `*` 收敛到实际本地前端 Origin；
- 不在反向代理或公网暴露 `/mcp`、密码 reveal 和数据源 API；
- 连接配置不写入仓库；
- 如果未来绑定 `0.0.0.0`、局域网或公网，必须暂停并重新评审鉴权、TLS、审计和 task token。

## 27. 可靠性、降级与功能开关

新增 Settings：

```text
database_tools_enabled
database_max_rows
database_max_result_bytes
database_max_query_timeout_ms
database_max_cached_connectors
database_max_concurrency_per_source
database_schema_result_bytes
```

发布策略：

- 初次集成时 `database_tools_enabled=false`；
- Connector、ClickHouse 管理和测试稳定后开启；
- 正式本地验收通过后默认 true；
- 关闭开关后 prepare 仍正常，只返回空 databases；
- 新数据库 Tool 返回 `database_tools_disabled`，原有文档工具完全不受影响；
- 业务数据库离线不能使应用启动失败；
- 数据库同步必须完整 discover 成功后再原子更新；
- Query 失败不修改 Source、Database 或 Link；
- 新 JSON 配置字段被旧代码自然忽略；
- migration 不回改历史版本，代码回滚时 nullable `mcp_alias` 不阻止旧代码写入。

## 28. 测试设计

### 28.1 单元测试

#### Resolver

- 合法 task -> project -> alias -> Link/Database/Source；
- task 不存在；
- 项目停用、删除或 path 改变；
- alias 不存在、大小写匹配和冲突；
- Link disabled 或 readonly=false；
- Source disabled；
- Database unavailable；
- Engine 不支持；
- 当前策略完整传递；
- 不能访问其他项目同名 alias。

#### SQL Policy

必须允许：

```sql
SELECT 1
WITH x AS (SELECT 1) SELECT * FROM x
SELECT * FROM allowed_table LIMIT 10
EXPLAIN SELECT * FROM allowed_table
DESCRIBE TABLE allowed_table
```

必须拒绝：

```sql
SELECT 1; DROP TABLE x
INSERT INTO x SELECT 1
CREATE TABLE x (id Int32)
SYSTEM FLUSH LOGS
SELECT * FROM other_database.secret
SELECT * FROM url('http://example.invalid')
SELECT * FROM file('/etc/passwd')
SELECT 1 SETTINGS readonly=0
SELECT 1 INTO OUTFILE '/tmp/x'
```

同时覆盖注释、字符串内分号、混合大小写、尾分号、CTE、嵌套子查询、quoted identifier、SQLGlot 解析失败和 table function。

#### 结果格式

- Int8 到 UInt256；
- 超过 JavaScript 安全范围的 UInt64；
- Decimal；
- Date、DateTime、DateTime64；
- UUID、IPv4、IPv6；
- Nullable；
- Array、Tuple、Map、Nested；
- bytes；
- NaN 和 Infinity；
- 重复列名；
- `max_rows + 1` 截断；
- 中文和 Emoji 的 UTF-8 字节预算；
- 单个大字段；
- 超大列元数据。

#### Manager 生命周期

- 启动零连接；
- lazy initialize；
- 20 个并发首次调用只初始化一次；
- 相同版本复用；
- config version 更新原子替换；
- 新连接 ping 失败不发布；
- 不回退旧配置；
- 活动查询完成前不 close；
- invalidate source；
- LRU 回收空闲连接；
- shutdown close all；
- close 幂等；
- 日志无密码或 DSN。

### 28.2 Repository 与 migration

- mcp_alias backfill 稳定；
- 项目内大小写无关唯一；
- 不同项目可复用同一别名；
- 非法格式拒绝；
- nullable 兼容旧写入；
- 调用记录 task 外键与级联删除；
- 数据库中不出现完整 SQL 和结果；
- upgrade -> current -> downgrade -> upgrade；
- 所有已有 Source、Database、Link、密码 JSON 和策略不丢失。

### 28.3 API 测试

- 创建、编辑 ClickHouse Source；
- password 列表过滤和 reveal no-store 回归；
- 空 password 保留旧值；
- Engine 能力接口；
- ClickHouse 连接测试成功、超时和认证失败；
- ClickHouse 数据库同步；
- 同步保留 Database 和 Link ID；
- 同步网络失败不误标全部 unavailable；
- mcp_alias 生成、编辑、冲突和格式校验；
- Source 更新增加 config_version；
- Query Policy API round-trip。

### 28.4 MCP 测试

- tools/list 恰好包含四个稳定工具；
- Tool 描述和输入 Schema；
- prepare 保持原文档结果并增加 databases；
- 无数据库关联时返回空数组；
- 数据库离线时 prepare/read 仍成功；
- search names/summary/full；
- execute SELECT；
- 写 SQL 返回稳定只读错误；
- task 与其他项目 alias 组合拒绝；
- 输出不包含 Connection Config；
- MCP 重连后使用 task_id 继续查询；
- 原有 read_context_document 完整回归。

### 28.5 ClickHouse 真实集成测试

根 Compose 增加带 `integration` profile 的固定版本 ClickHouse 测试服务，禁止使用 `latest`。所有测试仍通过当前 Docker Compose 执行，不引入宿主机 Testcontainers。

```bash
docker compose --profile integration up -d clickhouse-test
docker compose exec backend uv run --extra dev pytest -q -m clickhouse
docker compose --profile integration stop clickhouse-test
```

Fixture 使用管理员创建测试数据库、表、视图和只读用户；产品 Connector 只使用只读用户。覆盖：

- ping；
- system.databases 同步；
- table/view/column/index 的 names/summary/full；
- 参数化 glob 和 Unicode 名称；
- 普通 SELECT、聚合、CTE、DESCRIBE 和 EXPLAIN；
- 应用层拒绝 DDL/DML；
- 绕过应用层时只读账号仍拒绝写入；
- 跨库和外部 table function 拒绝；
- 1001+ 行、2 MB+ 字段和复杂类型；
- `sleepEachRow` 或等价慢查询超时；
- 远端 query 停止；
- ClickHouse 重启后重新连接；
- config version 切换和旧 Client 关闭；
- 20 个并发查询；
- ClickHouse 离线时 `/health` 和文档 MCP 继续可用。

TLS、CA 和 Cloud 行为第一版以配置单元测试为主，不让 CI 依赖公网服务。

### 28.6 前端与回归

- Engine 能力状态正确展示；
- ClickHouse TLS 字段、连接测试和同步；
- mcp_alias 编辑和错误提示；
- readonly=false 提示不暴露给 MCP；
- MCP 接入面板 tools/list 和端到端检查更新；
- 文档树、prepare/read、Task History、项目 CRUD、MySQL/PostgreSQL 同步全部回归。

标准验证命令：

```bash
docker compose restart backend
docker compose exec backend uv run --extra dev pytest -q
docker compose exec backend uv run --extra dev ruff check .
docker compose exec backend uv run --extra dev ruff format --check .
docker compose exec frontend npm run lint
docker compose exec frontend npm test
docker compose exec frontend npm run build
```

## 29. 资源与性能验收

不设置依赖具体硬件的严格 CI 延迟阈值，但必须验证资源有界：

- 记录首次连接和 warm `SELECT 1` 耗时；
- 记录 warm Schema search 的 p50/p95；
- 20 个并发查询期间 `/health` 和文档 MCP 仍能响应；
- Connector 缓存不超过配置上限；
- 单 Source 并发不超过配置上限；
- 100,000 行远端结果最终不超过 effective max rows；
- 最终 MCP 结果不超过 effective max bytes；
- 超时查询在策略时间附近终止；
- 连续 100 次查询后 Client、线程和后台任务数量不持续增长；
- shutdown 不出现 unclosed client/session 警告；
- 日志不打印密码、DSN、完整 SQL 或大结果。

性能检查标记为 `slow`/`clickhouse`，默认单元测试不依赖真实 ClickHouse；发布前必须运行完整 integration profile。

## 30. 分阶段实施顺序

### Phase 1：领域模型与基础设施

- mcp_alias migration 和 API 模型；
- Connector models、Protocol、Registry；
- DatabaseAccessService 和一次性 Repository JOIN；
- Query Policy 和 Result Formatter；
- ConnectorManager、lease、single-flight 和 lifespan close；
- Fake Connector 单元测试。

退出标准：不连接真实数据库即可完整验证项目路由、策略、Manager 和结果预算。

### Phase 2：ClickHouse 管理能力

- 添加 clickhouse-connect 和锁定依赖；
- ClickHouse Connection Config Pydantic 模型；
- ping、连接测试、system.databases 同步；
- 前端 TLS/Host/测试/同步；
- ClickHouse Compose profile 和基础集成测试。

退出标准：页面可以配置、验证并同步 ClickHouse，失败不破坏现有数据库清单。

### Phase 3：Schema 和只读查询

- ClickHouse system.tables/system.columns/system.data_skipping_indices；
- SQLGlot 单语句和只读策略；
- ClickHouse settings、query_id 和 timeout；
- 流式结果、复杂类型和 Token 预算；
- PostgreSQL/MySQL/MariaDB Connector 统一接入。

退出标准：Service 层可安全完成 search 和 bounded readonly query，所有绕过测试通过。

### Phase 4：MCP 与调用记录

- prepare 增加 databases；
- 注册两个数据库 Tool；
- 数据库调用元数据表和 Repository；
- MCP 自检增加可选数据库阶段；
- Tasks 页面接入客观数据库调用记录。

退出标准：Codex 和 Antigravity 可完成 `prepare -> search -> query`，文档工具无回归。

### Phase 5：能力状态、全量回归与启用

- Engine 能力接口和 UI 真值；
- feature flag 灰度开启；
- migration 往返；
- 后端、前端和 ClickHouse integration 全量验证；
- 更新业务、数据库、启动、链路和 Agent 使用文档；
- 正式把本地默认开关设为 true。

### Phase 6：按实际需求扩展

- SQLite；
- SQL Server；
- 查询历史体验优化；
- Router 元数据 SQLite 化；
- 只有在真实重复业务出现后评估固定参数化查询工具。

Phase 6 不属于本轮验收。

## 31. 最终验收标准

### 31.1 工具和路由

1. `tools/list` 始终恰好返回四个工具。
2. prepare 返回原文档树和当前项目可查询数据库摘要。
3. Agent 不传 Source ID、Database ID、Host、DSN 或限制参数。
4. task A 无法访问项目 B 的数据库 alias。
5. Link/Source 停用或 Database unavailable 后，已有 task 立即不能查询。
6. 项目路径改变后旧 task 提示重新 prepare。

### 31.2 SQL 安全

1. MCP 第一版无法执行任何写 SQL。
2. 多语句、跨库、SQL settings、文件输出和外部 table function 被拒绝。
3. PostgreSQL/MySQL/ClickHouse 都有数据库级只读兜底。
4. Agent 不能扩大行数、字节数、超时、扫描量、线程和内存限制。
5. 错误、日志和调用历史不包含密码或完整连接信息。

### 31.3 Token 与资源

1. names 响应明显小于 summary，summary 明显小于 full。
2. 查询返回列信息一次、rows 二维数组。
3. max rows、max bytes 和 timeout 实际生效。
4. 大整数、Decimal、时间、UUID、bytes 和 ClickHouse 复杂类型产生合法 JSON。
5. 大结果不会先完整物化到后端内存。

### 31.4 生命周期与降级

1. 应用启动后业务数据库连接数为 0。
2. 并发首次访问只创建一个 Connector。
3. 新配置连接验证成功后才切换，旧活动查询不被提前关闭。
4. Source 删除、停用和应用 shutdown 都关闭连接。
5. ClickHouse 离线不影响 `/health`、prepare 和 read。
6. 关闭 database tools feature flag 后原有 Context Router 完整可用。

### 31.5 交付质量

1. 后端 pytest、ruff check、ruff format check 全部通过。
2. 前端 lint、test、build 全部通过。
3. ClickHouse integration profile 全部通过。
4. migration upgrade/downgrade/upgrade 通过且数据无损。
5. Codex 和 Antigravity 使用同一个现有 MCP URL 完成真实端到端调用。
6. 业务功能、数据库信息、启动指南、前后端链路、架构决策、开发记录和 Agent 使用文档与实现一致。

## 32. 主要风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 旧 alias 空值或冲突 | 使用独立 nullable mcp_alias、稳定回填和部分唯一索引 |
| SQLGlot 拒绝合法方言 | fail-closed，返回可操作错误并补回归用例，不降级裸执行 |
| readonly 仍可读取文件/网络 | 禁止 table function、跨库和 system catalog，使用最小权限账号 |
| LIMIT 小但远端扫描巨大 | ClickHouse scan/memory/thread 限制和各 Engine server timeout |
| 驱动先物化大结果 | streaming cursor/row stream + 服务端结果限制 |
| 同步 I/O 阻塞 event loop | 在线程池执行并做 health 并发测试 |
| 配置更新时关闭活动查询 | lease/refcount + retiring 状态 |
| Python timeout 后远端继续跑 | V1 使用数据库 server timeout；保留 query_id，应用层主动取消列为后续增强 |
| 凭据出现在驱动异常 | 统一错误分类和日志清洗，不透传原异常 |
| 页面显示未实现 Engine 可查询 | 后端能力真值接口和明确 config-only 状态 |
| 数据库离线拖垮文档工具 | 全部 lazy、prepare 不 ping、feature flag 独立降级 |
| 方案直接复制第三方代码产生许可问题 | 只继承设计和测试场景，Python 重新实现；直接引用时保留许可 |

## 33. 实施完成时需要同步的文档

本设计落地后必须同步：

- `docs/BUSINESS_FEATURES.md`
- `docs/DATABASE_INFO.md`
- `docs/FRONTEND_BACKEND_FLOW.md`
- `docs/STARTUP_GUIDE.md`
- `docs/DEVELOPMENT_OUTLINE.md`
- `docs/development-details/ARCHITECTURE_DECISIONS.md`
- `docs/development-details/CODE_CHANGE_LOG.md`
- `docs/AI_CONTEXT_INDEX.template.md`
- `docs/managed/context-router-area-database.md`
- `docs/managed/context-router-prepare-guide.md`
- `docs/managed/context-router-routing-guide.md`
- MCP 接入面板中的 Codex/Antigravity 使用说明

在正式开发开始前，应根据本文再生成一份独立实施计划：

```text
docs/superpowers/plans/2026-07-22-database-context-mcp-implementation-plan.md
```

实施计划按测试先行方式拆分 Task，逐项列出修改文件、失败测试、最小实现、Docker Compose 验证和提交边界；不在本文中提前写死具体提交。
