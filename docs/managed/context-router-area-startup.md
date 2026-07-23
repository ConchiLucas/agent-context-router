# 启动与开发路由

## 适用任务

- 启动或重启前后端。
- 运行测试、lint、build 或 migration。
- 排查 Docker Compose 服务状态。
- 运行固定版本 ClickHouse integration profile。

## 下一层文档

| document_id | 用途 |
| --- | --- |
| `context-router-startup-guide` | 本仓库 Docker Compose 启动与验证规则 |
| `context-router-area-database` | migration 和数据库初始化 |

本项目只使用当前仓库 Docker Compose 管理服务，不直接在宿主机启动前后端。前后端宿主机端口只绑定回环地址；真实 ClickHouse 用例通过 `docker compose --profile integration` 启动 `clickhouse-test`，不使用宿主机 Testcontainers。
