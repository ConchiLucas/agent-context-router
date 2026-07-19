# 排障路由

## 适用任务

- Tasks 没有记录或调用链不完整。
- cwd 识别错项目、候选文档不准确。
- read 被拒绝、parent_document_id 校验失败。
- 页面、API、数据库数据不一致。

## 下一层文档

| document_id | 用途 |
| --- | --- |
| `context-router-routing-guide` | 确认任务和项目路由 |
| `context-router-trace-guide` | 确认 prepare/read 事件语义 |
| `context-router-area-backend` | 定位 MCP、API 和 service |
| `context-router-area-database` | 检查 trace 和 retrieval 数据 |

优先从 Tasks 详情确认事实，再沿 MCP -> API -> service -> database 逐层排查。
