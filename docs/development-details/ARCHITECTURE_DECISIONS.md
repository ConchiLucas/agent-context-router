# 架构决策记录

本文件记录会影响后续开发方式的技术决策和取舍。

## 记录规则

- 记录决策背景、最终选择和影响范围。
- 不记录普通聊天或临时讨论。

## 记录

### 2026-07-22

- MCP 工具集合固定为 `prepare_task_context`、`read_context_document`、`search_database_objects`、`execute_database_query` 四个；数据源增删不生成动态工具，保证 Codex 和 Antigravity 的工具发现结果稳定。
- 数据库访问统一经过 `task_id -> project_key -> 当前 project -> 项目内 mcp_alias -> live policy`。MCP 参数不接受 project/source/database ID、Host、DSN、口令或客户端自定义查询限制。
- `mcp_alias` 与人类展示 alias 分离，在项目内大小写无关唯一。prepare 只返回可用只读数据库的最小摘要，不连接远端业务数据库。
- 项目数据库选择与 alias 使用单次批量事务更新；事务内先释放旧 alias 再写入最终集合，以支持 A/B 互换并避免前端多请求造成部分状态。
- 第一版数据库 MCP 永久只读：SQLGlot fail-closed AST 与作用域校验、数据库只读事务/ClickHouse readonly settings、只读数据库账号共同构成防护；写 SQL、事务会话和自定义 SQL 工具不在本轮范围。
- Connector 使用静态 Registry 和能力矩阵；Manager lazy 创建、single-flight、发布前 ping、按 source version 与 database update 失效、lease/retiring、每 Source 并发限制和 LRU。应用启动不连接业务数据库，lifespan 退出统一关闭。
- 查询结果按最终 compact JSON UTF-8 字节和行数双重预算，复杂类型递归转为合法 JSON；完整 SQL 和结果不持久化，只记录 SQL SHA-256 与调用元数据。
- ClickHouse V1 使用官方 HTTP/HTTPS Client，支持连接测试、`system.databases` 同步、渐进对象搜索和有界只读查询；未实现 Connector 的 Engine 只允许配置，不在 UI 中伪装成可查询。
- 本项目是本机单用户工具，不增加 OAuth/RBAC；Backend 与 Frontend 端口必须只绑定 `127.0.0.1`。若未来暴露到局域网或公网，必须重新评审鉴权、TLS、CORS 和 task_id 的安全语义。

### 2026-07-19

- 采用“产品 MCP-only、HTTP API 内部保留”的边界，AI 只感知两个 MCP 工具，开发者只使用 Web 查看和管理。
- MCP 不维护全局当前 trace 或当前文档，所有 read 显式绑定 trace，避免多个 AI 任务并发串链。
- AI 可自主跳过 MCP；系统只记录实际 prepare/read，不增加人工反馈、任务成功评分或不读原因字段。
- 项目文档继续放在各自项目仓库，Context Router 只保存可同步索引；cwd 最长 root_path 匹配负责跨项目定位。
- Tasks 页面是可观察性产品，数据源只包含 MCP 任务，Web 文档预览保持 untracked。
- 旧表和 migration 保留历史兼容，运行时路由和页面可以删除。

### 2026-06-27

- 文档体系采用按需读取结构：`AGENTS.md` 只保留一级索引，`docs/DEVELOPMENT_OUTLINE.md` 负责开发大纲，细节放入 `docs/development-details/`。
- 上下文检索不再使用文档切分表或向量相关能力，统一基于完整文档正文和元数据做确定性关键词检索。
- 任务入口路由信息作为 trace 的一等元数据保存，包括 area、入口索引路径、入口规则、route hint、调用来源和 agent 名称。
- 显式传入 area 时，检索优先限定在相同 area 和通用文档内，避免 AI 为一个明确任务读取过多无关 area 的上下文。
