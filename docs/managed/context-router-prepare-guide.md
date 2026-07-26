# prepare_task_context 说明

## 何时调用

- 当前任务依赖工作空间或项目稳定说明，但新窗口没有上下文。
- 需要业务边界、启动规范、数据库信息或跨服务链路。
- 不确定应该先读哪份工作空间文档。

明确文件或代码符号时可以直接检索，不必为了留下记录而调用 MCP。

## 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `task` | 是 | 当前任务原文，不要改写成泛化关键词 |
| `cwd` | 是 | 当前工作目录，用于自动识别 Workspace，并在适用时标记 active project |
| `agent_name` | 否 | `codex`、`antigravity` 等调用方名称 |

每次调用由服务端生成独立 task_id，并返回 cwd 对应 Workspace 的文档导航树、Project 摘要和可选 active project。Workspace 根 `AGENTS.md` 存在时严格采用其显式父子层级，不自动追加未声明的 Project 根；不存在时返回直接列出 Project 入口的合成根。未进入显式树的 Project 文档仍可通过 `search_context_documents` 定位并按结果 ID 读取。节点只携带显式 Front Matter 中的 title 和 summary，不做候选检索、排名、截断或正文返回。

prepare 还返回当前 Workspace 可用于 MCP 的数据库摘要，即所有 Project 有效授权的并集，并保留 Project 归属信息。`database` 是 Workspace 内唯一的 `mcp_alias`，并带 Engine、展示名、用途、readonly 和 `search_objects`/`execute_query` 能力。它只读取控制面配置，不连接业务数据库；停用的 Workspace、无效关联、不可用或系统数据库、非只读授权以及未实现 Connector 的关联不会出现。数据库摘要暂时失败时返回 warning，文档树仍可使用。
