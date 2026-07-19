# read_context_document 说明

## 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `trace_id` | 是 | 来自当前任务的 prepare 返回 |
| `document_id` | 是 | 准备读取的候选文档 ID |
| `parent_document_id` | 否 | 从已读父文档继续向下时传入 |

## 规则

- 不要跨任务复用 trace_id。
- parent_document_id 必须是同一 trace 中更早读过的文档。
- 只读完成当前任务需要的文档，不要遍历全部候选。
- 文档内容与当前源码冲突时，以源码和实时配置为准。
- Web 预览使用 untracked 读取，不会伪装成 AI read 事件。
