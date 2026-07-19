# 启动与开发路由

本文件用于把启动、重启、构建、测试和本地验证类任务路由到合适上下文。

## 适用任务

- 启动前端或后端。
- 修改代码后重启服务。
- 运行 lint、build、测试或 migration。
- 排查本地 Docker Compose 服务状态。

## 子路由

- `startup`：启动、重启、端口和容器状态。
- `verification`：lint、build、测试和浏览器自测。
- `migration`：数据库迁移和表结构初始化。

## 下一层文档

| 文档 | 用途 | 命令 |
| --- | --- | --- |
| `context-router-area-database` | migration 和数据库初始化 | `ctx read context-router-area-database` |

启动和验证命令直接读 `docs/STARTUP_GUIDE.md`。
