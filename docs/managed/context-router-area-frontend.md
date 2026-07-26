# 前端路由

## 适用任务

- 首页 Workspace 管理、Workspace 文档树/MCP 接入/调用历史，以及子项目卡片管理。
- ClickHouse 配置/测试/同步、Engine 能力状态、Project 数据库授权和 Workspace 数据源汇总。
- 文档读取与数据库调用时间线、页面交互和浏览器验证。

## 代码入口

| 路径 | 用途 |
| --- | --- |
| `frontend/app/page.tsx` | 单页入口 |
| `frontend/components/workspace-dashboard.tsx` | Workspace 列表和创建/编辑入口 |
| `frontend/components/workspace-detail.tsx` | Workspace 工具栏、前后端 Project 页签和项目卡片 |
| `frontend/components/project-dashboard.tsx` | Project 编辑、数据源授权和删除 |
| `frontend/components/workspace-data-source-overview.tsx` | Workspace 数据源授权汇总 |
| `frontend/components/data-source-dashboard.tsx` | 数据源、ClickHouse 配置、能力、测试和同步 |
| `frontend/components/mcp-integration-panel.tsx` | Workspace MCP JSON、五工具、客户端配置和链路测试 |
| `frontend/lib/database-access.ts` | ClickHouse 配置 round-trip、别名校验、原子保存 payload 和调用时间线 |
| `frontend/lib/api.ts` | Next.js 到后端的数据请求 |

当前没有 Usage、反馈或任意 SQL 调试页面；调用历史不展示完整 SQL、参数或结果集。
