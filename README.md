# Agent Context Router

这是一个供本机 Codex、Antigravity 等 AI 工具使用的工作空间上下文路由器。它把一个绝对根目录作为 Workspace，在其中按相对路径配置一个或多个前端/后端 Project；工作空间根目录可用自己的 `AGENTS.md` 维护跨项目文档，每个项目也以自己的 `AGENTS.md` 为入口并拥有独立的数据源授权。Codex task、文档树、文档搜索/读取和数据库 alias 都以 Workspace 为边界，AI 不需要接触连接参数。

## 文档约定

工作空间和项目的根入口都固定命名为 `AGENTS.md`。工作空间根入口是可选的，不存在时继续使用合成工作空间根；需要下级文档时增加：

```markdown
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 后端架构、接口和服务说明 | `./docs/backend/backend.md` |
```

- 只有 `## 下级文档` 下的两列表格参与树映射。
- 相对路径以当前 Markdown 文件所在目录为基准。
- 路径必须以 `./` 开头、指向 `.md` 文件，并且不能越出当前目录。
- 下级文档可以继续声明自己的下级，目录深度不受限制。
- 正文中的普通 Markdown 链接不参与父子层级。

## 运行方式

Context Router 自身使用宿主机 Native Stack；注册到系统中的业务 Workspace 继续通过 Host Runner 使用各自的 Docker Compose：

本机工具链要求 Python 3.12、Node.js 22、uv、npm 和 Docker Desktop。macOS 可使用 `brew install node@22`；它无需替换系统其他 Node 版本，Native 脚本会优先发现 Homebrew 的 keg-only Node 22。

```bash
cp .env.native.example .env.native.local
./scripts/bootstrap-native.sh
./scripts/start-native-stack.sh
```

- Web：<http://127.0.0.1:49175>
- API：<http://127.0.0.1:49173>
- API 文档：<http://127.0.0.1:49173/docs>
- MCP：<http://127.0.0.1:49173/mcp>

Backend 直接读取 `CONTEXT_ROUTER_WORKSPACE_ROOT` 下的本机文档和源码，不预置任何工作空间或项目。其他机器通过 `.env.native.local` 覆盖：

```text
CONTEXT_ROUTER_WORKSPACE_ROOT=/absolute/workspace/root
CONTEXT_ROUTER_DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/context_router
```

页面可以长期维护多个工作空间、工作空间内的多个项目和全局物理数据源。工作空间保存绝对 `root_path` 和唯一运行时启停开关；项目只保存名称、`frontend/backend` 类型和工作空间内唯一的 `relative_path`，没有独立 enabled 状态。工作空间级入口固定为可选的 `root_path / AGENTS.md`；根项目使用 `.`，项目入口固定为 `root_path / relative_path / AGENTS.md`。工作空间/项目配置、项目数据库关联、Workspace MCP task、文档读取与数据库调用元数据保存在 PostgreSQL；后端重启时恢复配置并重新构建工作空间级及各项目缓存。真实工作空间入口严格定义导航树层级，缺少入口时合成根才列出 Project；全部项目文档始终保留在 Workspace 搜索和按 ID 读取范围。Markdown 原文仍以磁盘文件为唯一真源，数据库只额外保存用于词法检索的规范化派生分块，不保存文档工具完整出入参。数据库 MCP 工具的完整 SQL 与有界结果快照默认自动写入独立、可过期的 payload 表供本机链路页面按需查看。

物理数据源和数据库清单是全局配置，授权记录仍绑定到具体项目。Workspace task 可以使用目录下所有项目当前有效的授权，`mcp_alias` 在整个 Workspace 内大小写无关唯一；工作空间详情只聚合展示授权，不创建另一套工作空间级关联。当前版本由用户在工作空间详情中显式配置项目相对路径，不自动扫描目录注册项目。

## MCP 工具

MCP 始终暴露十个无状态工具：

- `prepare_task_context(task, cwd, agent_name?, environment?)`：按 cwd 定位 Workspace，创建 task_id；`environment` 可传该工作空间已登记的任意环境，省略时固定使用 `local`。
- `read_task_context(task_id, sections)`：任务需要时才返回数据库摘要或通用环境 JSON；它不是 Nacos 中间件实时信息的权威来源。
- `read_middleware_context(task_id, components?, reveal_secrets?)`：始终继承 prepare 固化的 task 环境；本机工具默认返回明文，只有显式 `reveal_secrets=false` 才脱敏。
- `search_context_documents(task_id, query, limit?)`：在 task 绑定 Workspace 的根文档和全部项目映射文档中，按路径、标题、概要、正文和章节做 PostgreSQL 全文与模糊检索；返回文档 ID、相关度、命中章节和命中原因，不返回完整正文。
- `read_context_document(task_id, requests)`：在 task 绑定 Workspace 的聚合缓存中一次读取 1 到 10 个文档或指定章节；task_id 必须来自当前任务的 prepare，返回顺序与 requests 一致。
- `resolve_database_target(task_id, mapping_id?, table_name?, business_hint?)`：解析并签发绑定 task、环境 revision 和物理库的短期 `database_context_id`。
- `search_database_objects(task_id, database_context_id, object_type, ...)`：按数据库上下文渐进搜索 schema、表、视图、列或索引。
- `execute_database_query(task_id, database_context_id, sql)`：执行一条经过 AST、数据库上下文作用域和数据库只读机制共同约束的查询，并按行数和最终 JSON 字节数截断。
- `execute_mapped_data_query(task_id, mapping_id, description, ...)`：原子执行已发布业务映射并把结果条件落到数据可视化，不需要传环境、库、Schema 或二次保存。
- `apply_workspace_changes(task_id, changed_files)`：按 Workspace 相对变更路径自动路由到受影响 Project，并选择 fast/full 更新。
- `start_workspace(task_id)`：通过 Workspace 唯一启动配置启动全部已登记服务。
- `get_workspace_operation(operation_id, log_characters?)`：查询 Workspace 异步运行操作、步骤、终态和有界日志。

导航树较大、目标不明确或目标 Project 未进入真实根显式树时，先调用 search，再用同一个 task_id 对命中文档或章节调用 read。检索会遍历 task 绑定 Workspace 的全部项目，但嵌套项目重复引用的文档只归最深项目所有，也不会把搜索结果当作正文。cwd 首先匹配最深 Workspace；其中最深 Project 仅作为活动项目快照，不会把文档或数据库权限收窄到该项目。工作空间停用或任一项目映射不可用时，新的 Workspace task 会明确失败。每次 read 由 PostgreSQL 生成 read_call_id，单次调用内按数组 position 记录顺序。数据库调用的常规审计记录只保存 alias、Engine、SQL SHA-256、状态、耗时和返回规模；完整 SQL 和最终有界结果会另存到默认保留 7 天的详情表。客户端不能通过 MCP 传入 Host、DSN、口令、数据库内部 ID 或放宽查询限制。

工作空间详情工具栏中的“刷新映射”“查看文档树”“查看 MCP JSON”和“查看调用记录”全部使用 Workspace API；MCP JSON 调用相同的 prepare service，调用记录按时间合并展示该工作空间 task 的文档读取和数据库对象搜索/查询历史。

首次使用前执行 migration：

```bash
UV_PROJECT_ENVIRONMENT=.venv-native uv run --directory backend alembic upgrade head
```

## 刷新行为

点击工作空间“刷新映射”时，后端先自动读取可选的 Workspace 根 `AGENTS.md`，再递归读取该 Workspace 下每个项目的 `AGENTS.md`；所有文档先在临时缓存中构建，再重建独立的 Workspace/Project PostgreSQL 词法索引并统一替换运行时缓存。任一入口构建失败时保留整个工作空间上一版映射；成功后显式根树或合成根树不会残留已删除节点或旧正文，未挂入真实根树的项目文档仍可搜索和读取。搜索严格校验参与范围的索引版本，索引缺失、构建失败或版本落后时返回明确错误，不回退到进程内扫描，也不会返回旧结果。

## 核心 API

| API | 作用 |
| --- | --- |
| `GET /api/workspaces` | 获取工作空间卡片与项目/数据源汇总数量 |
| `POST /api/workspaces` | 添加一个绝对根目录工作空间 |
| `GET /api/workspaces/{id}` | 获取单个工作空间及项目/授权计数 |
| `PUT /api/workspaces/{id}` | 修改工作空间名称、类型和根目录 |
| `PATCH /api/workspaces/{id}/enabled` | 设置工作空间总开关 |
| `DELETE /api/workspaces/{id}` | 删除工作空间及其项目配置 |
| `GET /api/workspaces/{id}/projects` | 获取工作空间内项目卡片 |
| `POST /api/workspaces/{id}/projects` | 按 `frontend/backend` 类型和相对路径添加项目 |
| `PUT /api/workspaces/{id}/projects/{project_id}` | 修改项目名称、类型和相对路径 |
| `DELETE /api/workspaces/{id}/projects/{project_id}` | 删除项目配置 |
| `POST /api/workspaces/{id}/refresh` | 全量重建工作空间内全部项目映射 |
| `GET /api/workspaces/{id}/tree` | 获取工作空间显式根树或合成根树 |
| `GET /api/workspaces/{id}/documents/{document_id}` | 从工作空间聚合缓存读取 Markdown |
| `POST /api/workspaces/{id}/prepare-preview` | 创建 Workspace 预览 task 并返回 MCP JSON |
| `GET /api/workspaces/{id}/tasks` | 获取工作空间最近 MCP task 与调用次数 |
| `GET /api/workspaces/{id}/environments` | 列出该工作空间独立拥有的动态环境；`local` 固定存在且为默认 |
| `GET /api/workspaces/{id}/data-source-summary?environment={key}` | 汇总所选环境关联的项目数据源授权 |
| `GET /api/workspaces/{id}/nacos-profiles` | 只读列出 Nacos 配置档摘要，不返回密码 |
| `PUT /api/workspaces/{id}/nacos-profiles/{environment}` | 由本机 AI/运维为已登记环境保存唯一 Nacos 连接与组件规则 |
| `GET /api/tasks/{task_id}/document-reads` | 获取任务的有序文档读取记录 |
| `GET /api/data-source-engines` | 获取各数据库 Engine 的配置、同步、搜索和查询能力 |
| `POST /api/data-sources/{id}/test` | 使用当前配置执行一次独立连接测试 |
| `PUT /api/projects/{project_id}/databases` | 原子保存项目数据库选择与全部 MCP alias |
| `PATCH /api/projects/{project_id}/databases/{link_id}/mcp-alias` | 修改数据库 alias；唯一性按所属 Workspace 校验 |
| `POST /api/mcp/integration/tests` | 对指定 Workspace 执行真实 MCP 连接测试 |

旧 `/api/projects` 仅保留兼容入口，`document_projects.agents_path/project_type` 也暂时保留；新的文档树、刷新、MCP JSON 和调用记录都只走 Workspace API。migration head 为 `20260820_0040`；`0040` 用动态 Workspace 环境替代固定 TEST/UAT 和逐 MCP 默认值，所有工作空间都以 `local` 为默认。升级前的 task 保持 `scope='project'` 兼容读取、搜索和数据库调用，历史记录继续可见。

开发、测试和重启命令见 [启动与开发规范](./docs/STARTUP_GUIDE.md)。
