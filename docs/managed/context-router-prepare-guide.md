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
| `environment` | 否 | 可传当前 Workspace 已登记的任意环境；省略时固定使用 `local` |

每次调用由服务端生成独立 task_id。存在真实 Workspace 根 `AGENTS.md` 时固定以它为第一层；缺少真实根时，才以 cwd 命中的 Project 入口或合成根为第一层。只返回入口在 `## 下级文档` 中显式声明的两级子孙，总高度最多三层。节点只含 `document_id`、`summary` 和 `children`，不返回正文，也不根据 task 内容搜索或排名。

这个三层树只是当前任务的精简导航，不是读取授权清单。更深文档、其他 Project 文档或未挂入真实 Workspace 根的 Project 文档，仍可通过同一 task_id 调用 Workspace 范围的 `search_context_documents`，再按结果 ID 调用 `read_context_document`。

prepare 不直接返回数据库摘要或环境 JSON。任务确实需要这些信息时，再调用 `read_task_context(task_id, sections)`；显式 `environment` 只固定当前 task，不修改 Workspace 默认环境。
