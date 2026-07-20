# Tasks 调用链说明

## 记录内容

- task_id、task、cwd、project、agent_name 和创建时间。
- 每次 read 的 read_call_id 和创建时间。
- 单次批量读取中每个文档的 position、document_id、相对路径、section、状态和错误码。

## 页面含义

- 项目卡片“查看调用记录”左侧列出任务，右侧按 read_call_id 和 position 从上到下展示实际读取。
- 同一次调用中的文档只表示请求顺序，不表示文档之间存在依赖关系。
- 页面展示成功与失败项，但数据库不保存 Markdown 正文。

系统不记录人工反馈，也不推测 AI 为什么没有继续阅读。开发者可通过长期链路分布判断文档标题、标签、拆分或路由是否需要优化。
