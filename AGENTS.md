# AGENTS.md

本文件是 AI 编程助手进入本仓库后的一级索引文档，保持简洁。先按任务选择文档，不要一次性读取全部细节。

## 启动本仓库

用户要求启动、重启 `agent-context-router` 时，只执行仓库脚本，不要手写 `uvicorn` / `next` / `docker compose`，也不要调用 MCP `start_workspace`（那是已注册业务 Workspace 的入口）。

```bash
./scripts/start-native-stack.sh      # 未运行
./scripts/restart-native-stack.sh    # 已运行，或刚改过后端
./scripts/status-native-stack.sh
./scripts/stop-native-stack.sh
```

正式前端只有 `http://127.0.0.1:49175`。不要再启动 `49174`，不要执行 `scripts/start-local-stack.sh` 里的旧 Docker 路径，也不要手写 `next dev --port 49174`。

## 文档索引

- [开发大纲](./docs/DEVELOPMENT_OUTLINE.md)：代码开发时先读，用于按需选择开发细节文档。
- [启动与开发规范](./docs/STARTUP_GUIDE.md)：启动、重启、测试、lint、build、migration。
- [数据库信息](./docs/DATABASE_INFO.md)：检查 bug、运行脚本、排查数据问题前先读取。
- [业务功能说明](./docs/BUSINESS_FEATURES.md)：需要理解项目目标、业务模块和功能边界时读取。
- [链路流转速查](./docs/FRONTEND_BACKEND_FLOW.md)：定位页面、接口、service、数据库链路时读取。
- [接口语义检索迁移验收](./docs/INTERFACE_SEARCH_ACCEPTANCE.md)：接口检索改动、MCP 渐进链路和准确率回归门槛。
- [按表名补全表关联](./docs/development-details/table_relation_complete.md)：用户给出表名时读取并执行；检查关系列表、关系详情、插入入口、更新入口，缺则自动补进种子并跑脚本。
- [表关联种子怎么写](./docs/development-details/table_relation_seed.md)：字段和枚举对照；补数据时改种子脚本，不要直接写 PostgreSQL。

## 核心规则

- 当前工作目录位于本仓库（Context Router 自身）时，不调用 Context Router MCP，包括 `prepare_task_context`、文档检索、数据库查询、运行编排和任务可视化等工具；直接依据本文件、`docs/` 文档、仓库源码及本仓库脚本完成检索、排查、开发和验证，避免用被开发系统反向管理自身。
- 只有处理 Context Router 已注册的其他业务 Workspace 时，才遵守该次 `prepare_task_context` 返回的 `workspace_rules`；本文件不复制控制面规则正文。
- 在其他已注册业务 Workspace 的新窗口中，遇到业务规则、启动、数据库或跨层链路任务时，优先调用 Context Router MCP `prepare_task_context`，传当前 task、cwd 和 agent_name；明确文件或纯源码定位可直接检索。
- MCP prepare 在真实 Workspace 根 `AGENTS.md` 存在时固定以它为第一层；缺少真实根时，才以 cwd 命中的 Project 入口或合成根为第一层。导航只返回显式下两级，总高度最多三层，每个节点只有 `document_id`、`summary` 和 `children`。这只是任务导航投影，不缩小 Workspace 搜索和按 ID 读取范围；目标不明确或未出现在投影中时，先用同一 task_id 调用 `search_context_documents`，再根据命中的 title、summary、path 和章节调用 `read_context_document`。只有任务需要数据库别名或环境 JSON 时才调用 `read_task_context`。
- 工作空间根目录存在 `AGENTS.md` 时，它是工作空间级文档树入口；各前端/后端 Project 的源码相对路径与文档入口相对路径彼此独立。新项目入口统一放在工作空间 `docs/` 层级下并命名为 `AGENTS.md`，独立进入 Workspace 检索和按搜索结果 ID 读取范围。不要把未声明的 Project 入口自动追加到真实根的直接下级。
- 工作空间和项目路径配置由本机 AI/运维 API 管理；工作空间级刷新可由 Workspaces 页面卡片触发。不要把工作空间 `root_path` 当成单个项目文档目录，也不要向刷新接口提交任意路径。
- 如果 MCP 不可用或没有合适候选，继续使用本索引和仓库检索，不要阻塞任务。
- 修改代码前先阅读相关文件和开发规范。
- Context Router 自身使用宿主机 Native 方式运行；不要用 Docker Compose 启动本项目的前端或后端。
- 已注册 Workspace 仍通过 Host Runtime Runner 执行各自的 Docker Compose 部署脚本；不要把业务 Workspace 改成 Native。
- 启动本仓库只走上面的 Native Stack 脚本。
- 修改后端代码后，开发模式依靠 Uvicorn reload；常驻模式按开发规范使用 `scripts/restart-native-stack.sh`。
- 后续自测、测试、lint、build、migration 都按开发规范在宿主机隔离环境执行；ClickHouse 集成测试可以单独使用 Docker。
- 只记录代码层面的开发内容，不记录普通聊天。
