# read_context_document 说明

## 参数

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `task_id` | 是 | 来自当前任务的 prepare 返回 |
| `requests` | 是 | 1 到 10 个文档读取项，按数组顺序返回 |
| `requests[].document_id` | 是 | prepare 完整树中的文档 ID |
| `requests[].section` | 否 | 精确 Markdown ATX 标题文本，不包含 `#` |

## 规则

- 不要跨任务复用 task_id；新对话没有 task_id 时重新 prepare。
- 同一次 read 可以读取多个互相没有关系的文档，不需要 parent_document_id。
- 服务端生成 read_call_id，数组位置作为单次调用顺序；Agent 不传 sequence。
- 只读完成当前任务需要的文档，不要遍历完整文档树。
- 文档内容与当前源码冲突时，以源码和实时配置为准。
- 完整文档过大时改用 section；服务端不静默截断，也不自动扩展其他文档。
