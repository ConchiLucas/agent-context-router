# 排障路由

本文件用于把 bug 检查、异常定位和历史开发决策类任务路由到合适上下文。

## 适用任务

- 用户要求检查 bug 或解释异常行为。
- 需要定位前后端调用链。
- 需要查看历史改动、架构决策或已知限制。
- 需要判断某个问题属于文档缺失、检索不准还是代码缺陷。

## 子路由

- `bug_triage`：问题归因和复现入口。
- `flow_trace`：前端、后端、CLI、MCP 到数据库的链路。
- `history`：代码变更记录和架构决策。
- `missing_context`：推荐文档缺失或不够准确。

## 下一层文档

| 文档 | 用途 | 命令 |
| --- | --- | --- |
| `context-router-routing-guide` | 判断问题属于哪个 area | `ctx read context-router-routing-guide` |
| `context-router-trace-guide` | 查看调用链记录含义 | `ctx read context-router-trace-guide` |

历史开发记录直接读 `docs/development-details/CODE_CHANGE_LOG.md`。

如果需要修改代码，先根据已读文档确认相关链路，再按源码实际状态排查。
