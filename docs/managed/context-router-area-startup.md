# 启动与开发路由

## 适用任务

- 启动或重启本仓库前后端和 Host Runner。
- 运行测试、lint、build 或 migration。
- 运行固定版本 ClickHouse integration profile。

## 下一层文档

| document_id | 用途 |
| --- | --- |
| `context-router-startup-guide` | 本仓库 Native Stack 启动与验证规则 |
| `context-router-area-database` | migration 和数据库初始化 |

本项目前后端和 Host Runner 只走仓库 Native Stack 脚本，不要用 Docker Compose，也不要调用 MCP `start_workspace`。用户要求启动本仓库时执行 `./scripts/start-native-stack.sh`；已运行则执行 `./scripts/restart-native-stack.sh`。Docker 只用于已注册业务 Workspace 和 ClickHouse 集成测试。
