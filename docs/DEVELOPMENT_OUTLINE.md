# 开发大纲

修改代码前先读取 [启动与开发规范](./STARTUP_GUIDE.md)，所有运行和验证均通过 Docker Compose。

## 任务路由

| 任务 | 文档 | 主要代码 |
| --- | --- | --- |
| 产品目标和文档格式 | [业务功能说明](./BUSINESS_FEATURES.md) | `services/document_tree.py` |
| 页面、API 和缓存链路 | [前后端链路速查](./FRONTEND_BACKEND_FLOW.md) | `project-dashboard.tsx`、`api/projects.py` |
| 启动、测试、lint、build | [启动与开发规范](./STARTUP_GUIDE.md) | `docker-compose.yml` |
| 数据库相关判断 | [数据库信息](./DATABASE_INFO.md) | `repositories/`、`migrations/` |

## 当前架构约束

- 根入口文件必须命名为 `AGENTS.md`。
- 文档层级只来自 `## 下级文档` 下的“功能说明 / 相对路径”表格。
- 映射由普通代码完成，不调用大模型。
- 项目、文档树和正文保存在单个后端进程内；PostgreSQL 只保存 MCP 任务和读取顺序。
- 刷新是全量重建和原子替换。
- 前端只从树接口获取概览，从详情接口按需获取内存正文。
- 文档读取目录通过 Docker 只读挂载。
