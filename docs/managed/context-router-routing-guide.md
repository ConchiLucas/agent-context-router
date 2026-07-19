# 上下文路由规则

本文件说明任务类型如何对应到下一层文档。

## 下一层文档

| area | 文档 | 适用任务 | 命令 |
| --- | --- | --- | --- |
| `startup` | `context-router-area-startup` | 启动、重启、构建、测试、本地验证 | `ctx read context-router-area-startup` |
| `database` | `context-router-area-database` | 连接、建库、migration、数据检查 | `ctx read context-router-area-database` |
| `frontend` | `context-router-area-frontend` | 页面、交互、弹窗、浏览器自测 | `ctx read context-router-area-frontend` |
| `backend` | `context-router-area-backend` | API、检索、trace、CLI、MCP | `ctx read context-router-area-backend` |
| `business` | `context-router-area-business` | 产品能力、工作流、文档边界 | `ctx read context-router-area-business` |
| `debugging` | `context-router-area-debugging` | bug、调用链、历史决策、缺失上下文 | `ctx read context-router-area-debugging` |

## 兜底检索

如果任务无法对应到上面的 area，再使用：

```bash
ctx prepare --project rob-english-word-workforce
```

路由文档只负责让 AI 选择正确下一层，不保存大量源码、配置或表结构细节。
