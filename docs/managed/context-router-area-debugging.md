# 排障路由

## 适用任务

- Tasks 没有记录或调用链不完整。
- cwd 识别错项目、文档树不准确或 read 被拒绝。
- prepare 没返回预期数据库别名、别名解析失败或 Engine 能力不符。
- 连接测试、数据库同步、对象搜索、只读查询、截断或超时异常。
- 页面、API、数据库数据不一致。

## 下一层文档

| document_id | 用途 |
| --- | --- |
| `context-router-routing-guide` | 确认任务和项目路由 |
| `context-router-trace-guide` | 确认 prepare/read/database call 记录语义 |
| `context-router-area-backend` | 定位 MCP、API 和 service |
| `context-router-area-database` | 检查 trace 和 retrieval 数据 |

优先从 Tasks 详情确认事实，再沿 MCP -> service -> repository/Connector -> database 逐层排查。数据库问题同时检查 Engine 能力接口、项目关联是否 readonly、mcp_alias、数据源/库可用状态和当前配置版本；不要用完整 SQL 或密码换取调试便利。
