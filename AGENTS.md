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
- MCP 返回候选文档后，只对当前任务需要的内容调用 `read_context_document`，不要一次读取全部文档。
- 如果 MCP 不可用或没有合适候选，继续使用本索引和仓库检索，不要阻塞任务。
- 修改代码前先阅读相关文件和开发规范。
- 本项目只使用当前目录下的 Docker Compose 管理服务；不要用宿主机直接启动前端或后端。
- 修改后端代码后，按开发规范使用 `docker compose restart backend` 重启后端。
- 用户要求启动前后端时，按开发规范使用 Docker Compose 启动；如果已启动则重启。
- 后续自测、测试、lint、build、migration 都按开发规范走 Docker Compose。
- 只记录代码层面的开发内容，不记录普通聊天。
