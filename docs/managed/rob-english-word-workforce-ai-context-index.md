# rob-english-word-workforce 上下文索引

## 使用方式

- 调用 `prepare_task_context` 时传当前 task 和 workspace 内的 cwd。
- 系统根据 root path 识别父项目或最具体子项目。
- 从返回候选中选择需要的文档，再调用 `read_context_document`。
- 跨服务任务可从父项目开始；明确子项目任务可直接在子项目 cwd 下调用。

## 任务路由

| area | document_id | 适用任务 |
| --- | --- | --- |
| `startup` | `context-router-area-startup` | 启动、构建、测试和本地环境 |
| `database` | `rob-english-word-workforce-database-info` | PostgreSQL、Redis、表和数据 |
| `frontend` | `context-router-area-frontend` | Vue、React 页面和前后端接口 |
| `backend` | `context-router-area-backend` | Java、Go、Python 服务和 API |
| `business` | `rob-english-word-workforce-subprojects-overview` | 子项目职责和产品功能 |
| `debugging` | `rob-english-word-workforce-flow-overview` | 跨服务调用链和异常定位 |

## 子项目概览文档

| document_id | 子项目 |
| --- | --- |
| `rob-english-word-back-overview` | Java 后端 |
| `rob-english-word-front-overview` | Vue 主前端 |
| `rob-english-word-cloze-web-overview` | React 完形填空前端 |
| `word-select-dashboard-server-overview` | Go dashboard server |
| `word-select-dashboard-web-react-overview` | React dashboard |
| `word-agent-overview` | Python agent |
| `rob-english-word-scripts-overview` | workspace 辅助脚本 |
