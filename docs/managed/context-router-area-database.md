# 数据库路由

本文件用于把数据库连接、初始化、迁移和数据检查类任务路由到合适上下文。

## 适用任务

- 创建或检查本地 PostgreSQL 数据库。
- 初始化表结构或执行 Alembic migration。
- 读取数据库连接信息。
- 排查数据库连接、权限、端口或数据缺失问题。

## 子路由

- `database_connection`：连接地址、账号、端口和容器数据库。
- `schema_migration`：migration、表结构初始化和版本检查。
- `data_check`：数据存在性、文档入库和 trace 记录检查。

## 下一步

- 连接和服务信息读 `docs/DATABASE_INFO.md`。
- migration 读 `backend/alembic/versions/`。
- ORM 表结构读 `backend/src/context_router/db/models.py`。
- 当前数据库状态可以直接连接本地 PostgreSQL 检查。

如果需要真实表结构或配置细节，AI 可以直接读取项目目录或连接本地数据库，不必把这些细节长期保存成受管文档。
