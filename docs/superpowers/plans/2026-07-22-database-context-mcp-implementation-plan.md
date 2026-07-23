# Database Context MCP Implementation Plan

> **For agentic workers:** 按任务顺序实施。每个任务先补失败测试，再写最小实现；所有运行、测试、lint、build 和 migration 都必须通过本仓库 Docker Compose。

**Goal:** 在保留现有文档 Context Router 的前提下，为 Codex 和 Antigravity 增加项目作用域内的数据库摘要、渐进 Schema 搜索和有界只读查询，并完整支持 ClickHouse。

**Architecture:** 所有数据库调用固定经过 `task_id -> project -> mcp_alias -> live policy -> ConnectorManager -> Connector`。MCP 只暴露四个静态工具；Connector 不感知 MCP 和项目；业务数据库连接 lazy 创建，prepare 不访问远端数据库。

**Tech Stack:** Python 3.12、FastAPI、FastMCP、Pydantic、psycopg、PyMySQL、clickhouse-connect、SQLGlot、Alembic、pytest、Next.js、React、TypeScript、Docker Compose。

**Source design:** `docs/superpowers/specs/2026-07-22-database-context-mcp-design.md`

**Implementation status:** 2026-07-22 已完成；下列任务均已通过 Docker Compose 单元、真 PostgreSQL、真 ClickHouse、MCP ClientSession 与前端构建验收。

---

## Task 1: Migration 与稳定 MCP Alias

**Files:**

- Create: `backend/migrations/versions/20260722_0008_add_database_mcp_persistence.py`
- Modify: `backend/src/context_router/repositories/data_source_repository.py`
- Modify: `backend/src/context_router/schemas/data_sources.py`
- Modify: `backend/tests/test_data_source_management_api.py`

- [x] 先增加旧 Link 回填、格式校验、项目内大小写无关唯一和 migration 往返测试。
- [x] 新增 nullable `project_databases.mcp_alias`、部分唯一索引和约束，不修改历史 migration。
- [x] 自动别名按 alias、display name、remote name、稳定 ID 后缀生成。
- [x] Repository 的 create/replace 返回实际保存的别名；原有人类显示 alias 保持不变。
- [x] 通过 Compose 运行目标 API 测试和 Alembic upgrade/current/downgrade/upgrade。

**Commit boundary:** `feat: add stable project database MCP aliases`

## Task 2: 数据库调用元数据与一次性解析

**Files:**

- Modify: `backend/migrations/versions/20260722_0008_add_database_mcp_persistence.py`
- Create: `backend/src/context_router/repositories/database_call_repository.py`
- Modify: `backend/src/context_router/repositories/data_source_repository.py`
- Create: `backend/tests/test_database_call_repository.py`
- Modify: `backend/tests/test_data_source_management_api.py`

- [x] 先测试 task 外键、级联删除、SQL hash、状态和不保存 SQL/结果。
- [x] 新增 `mcp_database_calls` 及 task/id 索引。
- [x] 增加按 project + mcp_alias 的一次 JOIN 解析和 prepare 列表查询。
- [x] In-memory 与 PostgreSQL Repository 保持相同语义。
- [x] 验证其他项目同名 alias 不可被当前任务解析。

**Commit boundary:** `feat: resolve and record project database calls`

## Task 3: Connector 核心模型与 Registry

**Files:**

- Create: `backend/src/context_router/database/models.py`
- Create: `backend/src/context_router/database/protocol.py`
- Create: `backend/src/context_router/database/registry.py`
- Create: `backend/tests/test_database_registry.py`

- [x] 先测试重复注册、未知 Engine、能力矩阵和敏感配置不进入 repr。
- [x] 定义不可变 ConnectorSpec、Capabilities、Policy、Search/Query 原始结果。
- [x] 定义窄同步 Protocol：ping、discover、search、execute、close。
- [x] Registry 只按 Engine 注册 Factory，不生成动态 MCP Tool。

**Commit boundary:** `feat: add database connector registry`

## Task 4: SQL 安全和结果预算

**Files:**

- Create: `backend/src/context_router/database/policy.py`
- Create: `backend/src/context_router/database/result.py`
- Create: `backend/tests/test_database_policy.py`
- Create: `backend/tests/test_database_result.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/uv.lock`

- [x] 先覆盖只读语句、多语句、跨库、Schema 白名单、SETTINGS、OUTFILE 和 table function 绕过。
- [x] 使用 SQLGlot 对对应方言 fail-closed；解析失败绝不裸执行。
- [x] 有效限制取项目策略与服务硬上限最小值。
- [x] 递归序列化 Decimal、大整数、时间、UUID、bytes、Array、Tuple、Map、NaN/Infinity。
- [x] 按 compact JSON UTF-8 大小和 `max_rows + 1` 准确截断。

**Commit boundary:** `feat: enforce bounded readonly database queries`

## Task 5: ConnectorManager 生命周期

**Files:**

- Create: `backend/src/context_router/database/manager.py`
- Create: `backend/tests/test_connector_manager.py`
- Modify: `backend/src/context_router/config.py`

- [x] 先测试零启动连接、single-flight、失败不缓存、make-before-break、lease、retiring、LRU、invalidate 和幂等 shutdown。
- [x] 缓存键包含 source id/version 和 database id/updated_at。
- [x] 发布前 ping；配置变更后新请求不得静默回退旧凭据。
- [x] 锁只保护 Manager 状态，不覆盖远端查询。
- [x] 添加缓存、行数、字节、超时、并发和 Schema 响应 Settings。

**Commit boundary:** `feat: manage lazy database connector lifecycle`

## Task 6: ClickHouse 管理连接与数据库同步

**Files:**

- Create: `backend/src/context_router/database/connectors/clickhouse.py`
- Modify: `backend/src/context_router/services/database_discovery.py`
- Modify: `backend/src/context_router/api/data_sources.py`
- Modify: `backend/src/context_router/schemas/data_sources.py`
- Modify: `backend/tests/test_database_discovery.py`
- Modify: `backend/tests/test_data_source_management_api.py`

- [x] 先测试 HTTP/HTTPS、端口、verify、bootstrap database、超时、密码清洗和关闭。
- [x] 使用 clickhouse-connect；`system.databases` 完整成功后才原子同步。
- [x] 增加 Engine 能力接口与 `POST /data-sources/{id}/test`。
- [x] 连接测试不泄露 Host、DSN、密码或驱动堆栈。
- [x] 同步失败保持上一份数据库清单。

**Commit boundary:** `feat: manage and discover ClickHouse sources`

## Task 7: ClickHouse Schema 与只读查询

**Files:**

- Modify: `backend/src/context_router/database/connectors/clickhouse.py`
- Create: `backend/tests/test_clickhouse_connector.py`
- Modify: `docker-compose.yml`

- [x] 先用 Fake Client 测 names/summary/full、参数绑定、复杂类型和 settings。
- [x] Catalog 只查询 `system.tables`、`system.columns`、`system.data_skipping_indices`。
- [x] 普通查询强制 readonly、执行时间、结果、扫描、线程和内存限制。
- [x] 使用行流避免完整物化，并让 Formatter 决定最终响应预算。
- [x] 为 integration profile 增加固定版本 ClickHouse 与 healthcheck。

**Commit boundary:** `feat: query ClickHouse through bounded connectors`

## Task 8: PostgreSQL、MySQL 与 MariaDB 统一 Connector

**Files:**

- Create: `backend/src/context_router/database/connectors/postgresql.py`
- Create: `backend/src/context_router/database/connectors/mysql.py`
- Create: `backend/tests/test_relational_connectors.py`

- [x] 先测试连接绑定目标数据库、Catalog 参数、只读事务、timeout 和 streaming cursor。
- [x] PostgreSQL 使用 pg_catalog/information_schema 和 read-only transaction。
- [x] MySQL/MariaDB 共用主体、保留方言，并拒绝跨 database。
- [x] 不用 COUNT(*) 生成 Schema 摘要。

**Commit boundary:** `feat: unify relational database connectors`

## Task 9: DatabaseAccessService 与工具编排

**Files:**

- Create: `backend/src/context_router/services/database_access.py`
- Create: `backend/src/context_router/services/database_catalog.py`
- Create: `backend/src/context_router/services/database_query.py`
- Create: `backend/src/context_router/schemas/database_tools.py`
- Create: `backend/tests/test_database_services.py`

- [x] 先测试 task/project/alias/current status 的唯一解析通道和错误码。
- [x] 每次调用读取当前状态与策略，不冻结 prepare 时快照。
- [x] Service 组合 policy、Manager lease、Connector、Formatter 和调用记录。
- [x] 数据库失败不修改 Source/Database/Link，也不隐式重试 SQL。

**Commit boundary:** `feat: route project-scoped database operations`

## Task 10: Prepare 与四个 MCP 工具

**Files:**

- Modify: `backend/src/context_router/schemas/context.py`
- Modify: `backend/src/context_router/services/context_preparation.py`
- Modify: `backend/src/context_router/mcp_server.py`
- Modify: `backend/src/context_router/main.py`
- Modify: `backend/src/context_router/services/mcp_integration.py`
- Modify: `backend/tests/test_context_preparation.py`
- Modify: `backend/tests/test_mcp_server.py`
- Modify: `backend/tests/test_mcp_integration_api.py`

- [x] 先测试 prepare 空数据库、筛选状态、远端离线不影响文档和四个稳定 Tool。
- [x] prepare 只读控制面摘要，不 ping 远端。
- [x] 注册 `search_database_objects` 和 `execute_database_query`，参数不得包含连接与限制字段。
- [x] ToolError 只返回稳定 code 和短消息。
- [x] lifespan 关闭 Manager；feature flag 关闭时文档工具完整可用。

**Commit boundary:** `feat: expose project database context over MCP`

## Task 11: 前端 ClickHouse 与 MCP Alias 管理

**Files:**

- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/components/data-source-dashboard.tsx`
- Modify: `frontend/components/project-dashboard.tsx`
- Modify: `frontend/components/mcp-integration-panel.tsx`
- Modify: `frontend/app/globals.css`

- [x] 先补纯函数或组件可测逻辑，确保配置 round-trip 不丢字段。
- [x] ClickHouse 编辑支持 TLS、verify、bootstrap database、timeout、连接测试和同步。
- [x] 展示后端 Engine 能力真值，不把 config-only Engine 标为可查询。
- [x] 项目数据库展示和编辑 mcp_alias；readonly=false 明确提示不暴露给 MCP。
- [x] MCP 面板展示四个 Tool 和数据库可用性。

**Commit boundary:** `feat: manage ClickHouse MCP access in the web UI`

## Task 12: 真实集成、回归与文档

**Files:**

- Create: `backend/tests/test_clickhouse_integration.py`
- Create: `backend/tests/test_postgres_persistence_integration.py`
- Create: `backend/tests/test_relational_schema_disclosure.py`
- Modify: `docs/BUSINESS_FEATURES.md`
- Modify: `docs/DATABASE_INFO.md`
- Modify: `docs/FRONTEND_BACKEND_FLOW.md`
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/DEVELOPMENT_OUTLINE.md`
- Modify: `docs/development-details/ARCHITECTURE_DECISIONS.md`
- Modify: `docs/development-details/CODE_CHANGE_LOG.md`
- Modify: `docs/managed/*`

- [x] 真库验证 discover、Schema、SELECT、复杂类型、行/字节/超时、只读用户和离线降级。
- [x] 执行 migration upgrade/current/downgrade/upgrade 并核对数据无损。
- [x] 执行后端全量 pytest、ruff check、ruff format check。
- [x] 执行前端 lint、test、build。
- [x] 用真实 MCP ClientSession 完成 prepare -> search -> query -> read。
- [x] 更新所有当前功能文档，明确未实现 Engine 和本地回环边界。

**Compose verification:**

```bash
docker compose restart backend
docker compose exec backend uv run alembic upgrade head
docker compose exec backend uv run --extra dev pytest -q
docker compose exec backend uv run --extra dev ruff check .
docker compose exec backend uv run --extra dev ruff format --check .
docker compose exec frontend npm run lint
docker compose exec frontend npm test
docker compose exec frontend npm run build
docker compose --profile integration up -d clickhouse-test
docker compose exec backend uv run --extra dev pytest -q -m clickhouse
docker compose --profile integration stop clickhouse-test
```

**Commit boundary:** `docs: document database context MCP delivery`
