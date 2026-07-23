# prepare_task_context 说明

## 何时调用

- 当前任务依赖项目稳定说明，但新窗口没有上下文。
- 需要业务边界、启动规范、数据库信息或跨服务链路。
- 不确定应该先读哪份项目文档。

明确文件或代码符号时可以直接检索，不必为了留下记录而调用 MCP。

## 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `task` | 是 | 当前任务原文，不要改写成泛化关键词 |
| `cwd` | 是 | 当前工作目录，用于自动识别项目 |
| `agent_name` | 否 | `codex`、`antigravity` 等调用方名称 |

每次调用由服务端生成独立 task_id，并返回 cwd 对应项目的完整文档树。节点只携带显式 Front Matter 中的 title 和 summary，不做候选检索、排名、截断或正文返回。

prepare 还返回当前项目可用于 MCP 的数据库摘要：`database` 是项目内 `mcp_alias`，并带 Engine、展示名、用途、readonly 和 `search_objects`/`execute_query` 能力。它只读取控制面配置，不连接业务数据库；停用、不可用、系统库、非只读或未实现 Connector 的关联不会出现。数据库摘要暂时失败时返回 warning，文档树仍可使用。
