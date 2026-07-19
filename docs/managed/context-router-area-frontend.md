# 前端路由

## 适用任务

- Dashboard、Projects、Documents、Tasks 页面。
- 外层任务列表和独立调用链详情布局。
- 项目网页创建、文档同步和浏览器验证。

## 代码入口

| 路径 | 用途 |
| --- | --- |
| `frontend/app/tasks/` | Tasks 列表和详情路由 |
| `frontend/components/task-list.tsx` | 外层任务列表 |
| `frontend/components/task-detail.tsx` | prepare/read 调用链 |
| `frontend/app/projects/` | 项目网页管理 |
| `frontend/lib/api.ts` | Next.js 到后端的数据请求 |

当前没有 Traces、Usage 或反馈页面。
