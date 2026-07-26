# search_context_documents 说明

当 prepare 返回的导航树较大、目标文档不明确、目标 Project 未进入真实根显式树或需要按业务术语定位章节时，调用：

```text
search_context_documents(task_id, query, limit?)
```

| 参数 | 必填 | 规则 |
| --- | --- | --- |
| `task_id` | 是 | 当前任务的 prepare 返回值，不跨任务复用 |
| `query` | 是 | 去除首尾空白后 1 到 200 个字符 |
| `limit` | 否 | 返回文档数，默认 10，范围 1 到 50 |

搜索范围固定为 task 绑定 Workspace 的可选根文档和全部 Project 映射文档，覆盖路径、显式 title、显式 summary、章节标题和规范化正文。根入口与 Project 重叠时 Workspace 优先，Project 之间由最深 Project 归属；结果按文档去重，包含 document_id、path、title、summary、relevance、matched_sections 和 match_reasons，不会返回 Markdown 正文或正文摘录。

命中后继续使用同一个 task_id 调用 `read_context_document`。`matched_sections[].can_read_section=true` 时可以把对应 section 精确传给 read；否则读取整份文档或选择其他唯一章节。

第一版使用 PostgreSQL `simple` 全文检索与 `pg_trgm`，中文短词补充精确子串匹配，不使用向量数据库。Workspace 根文档与 Project 文档使用独立索引表；搜索只接受与当前内存文档版本一致的持久化派生索引。索引缺失、构建失败或版本落后会显式失败，不回退到内存扫描，也不会返回旧结果。
