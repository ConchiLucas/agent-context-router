# 后续优化计划

当前版本已建立 `prepare -> search -> read` 的文档闭环，并记录进入本服务的五个 MCP 工具调用。

## P0：实际使用验证

- 在 Codex 和 Antigravity 中统一配置同一个 MCP server。
- 观察新窗口是否能按 task + cwd 命中正确项目。
- 用 Tasks 详情观察入口是 `Entry returned` 还是 `Entry read`，以及后续实际阅读分支。
- 根据实际任务调整 title、tags、area 和文档拆分，不增加人工反馈字段。

## P1：链路可读性

- Tasks 增加项目、AI 工具和时间范围筛选。
- 长任务支持折叠入口和 read 分支。
- 明确展示 MCP API 错误事件，但不要求 AI填写停止原因。

## P2：检索质量

- 建立固定任务集，评估 PostgreSQL FTS + pg_trgm 的召回率、Top N 排序和 search -> read 文件访问量。
- 优先调整字段权重、中文短词、路径/章节命中和重复文档聚合，不改变 task 项目边界。
- 只有词法检索验证出稳定缺口时，再评估向量召回并与现有结果做混合排序；不直接替换确定性词法索引。

## 暂不做

- 成功率、任务完成评分、人工 useful/missing 反馈。
- 强制每个任务调用 MCP。
- 记录 AI 不读或停止阅读的主观原因。
- 删除历史数据库列和 migration。
