# 前端路由

## 适用任务

- 首页项目管理、数据源管理、文档树、MCP 接入和调用历史。
- ClickHouse 配置/测试/同步、Engine 能力状态和项目 mcp_alias 编辑。
- 文档读取与数据库调用时间线、页面交互和浏览器验证。

## 代码入口

| 路径 | 用途 |
| --- | --- |
| `frontend/app/page.tsx` | 单页入口 |
| `frontend/components/project-dashboard.tsx` | 项目、数据库授权、文档树和调用历史 |
| `frontend/components/data-source-dashboard.tsx` | 数据源、ClickHouse 配置、能力、测试和同步 |
| `frontend/components/mcp-integration-panel.tsx` | 四工具、客户端配置和文档链路测试 |
| `frontend/lib/database-access.ts` | ClickHouse 配置 round-trip、别名校验、原子保存 payload 和调用时间线 |
| `frontend/lib/api.ts` | Next.js 到后端的数据请求 |

当前没有 Usage、反馈或任意 SQL 调试页面；调用历史不展示完整 SQL、参数或结果集。
