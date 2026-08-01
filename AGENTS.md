# AGENTS.md

本文件是 AI 编程助手进入本仓库后的一级索引文档，保持简洁。先按任务选择文档，不要一次性读取全部细节。

## 文档索引

- [开发大纲](./docs/DEVELOPMENT_OUTLINE.md)：代码开发时先读，用于按需选择开发细节文档。
- [启动与开发规范](./docs/STARTUP_GUIDE.md)：启动、重启、测试、lint、build、migration。
- [数据库信息](./docs/DATABASE_INFO.md)：检查 bug、运行脚本、排查数据问题前先读取。
- [业务功能说明](./docs/BUSINESS_FEATURES.md)：需要理解项目目标、业务模块和功能边界时读取。
- [链路流转速查](./docs/FRONTEND_BACKEND_FLOW.md)：定位页面、接口、service、数据库链路时读取。

## 核心规则

- 新窗口遇到业务规则、启动、数据库或跨层链路任务时，优先调用 Context Router MCP `prepare_task_context`，传当前 task、cwd 和 agent_name；明确文件或纯源码定位可直接检索。
- MCP prepare 返回匹配工作空间的文档导航树；真实根 `AGENTS.md` 存在时严格采用其显式层级，缺少根入口时才用合成根列出 Project。cwd 落在某个子项目时还会标记 active project。目标不明确或目标 Project 未进入显式树时，先用同一 task_id 调用 `search_context_documents`，再根据命中的显式 title、summary、path 和章节调用 `read_context_document`。
- 工作空间根目录存在 `AGENTS.md` 时，它是工作空间级文档树入口；各前端/后端 Project 的源码相对路径与文档入口相对路径彼此独立。新项目入口统一放在工作空间 `docs/` 层级下并命名为 `AGENTS.md`，独立进入 Workspace 检索和按搜索结果 ID 读取范围。不要把未声明的 Project 入口自动追加到真实根的直接下级。
- 工作空间和项目路径配置由本机 AI/运维 API 管理；工作空间级刷新可由 Workspaces 页面卡片触发。不要把工作空间 `root_path` 当成单个项目文档目录，也不要向刷新接口提交任意路径。
- 如果 MCP 不可用或没有合适候选，继续使用本索引和仓库检索，不要阻塞任务。
- 修改代码前先阅读相关文件和开发规范。
- 本项目只使用当前目录下的 Docker Compose 管理服务；不要用宿主机直接启动前端或后端。
- 修改后端代码后，按开发规范使用 `docker compose restart backend` 重启后端。
- 用户要求启动前后端时，按开发规范使用 Docker Compose 启动；如果已启动则重启。
- 后续自测、测试、lint、build、migration 都按开发规范走 Docker Compose。
- 只记录代码层面的开发内容，不记录普通聊天。
