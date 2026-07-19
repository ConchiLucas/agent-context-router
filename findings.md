# Findings & Decisions

## Requirements
- 新任务/新窗口能可靠获得相关项目文档。
- Codex 更快、更准确地定位任务所需文档。
- 可以查看每个任务推荐和阅读了哪些文档及其顺序。
- trace 能支持后续优化文档内容、入口和路由规则。
- 基于用户刚拉取的最新代码重新判断，而非沿用旧版本结论。
- 开发者不会使用任何命令行；开发者只通过前端直观看到任务、阅读链路、推荐质量和实际效果。
- Codex、Antigravity 等 agent 工具应统一通过机器接口使用能力，不能依赖人工设置 `$CTX`、`SESSION_ID` 或运行同步命令。
- 用户确认正式统一为 MCP 方式，目标是比较 MCP 对 Agent 文档发现效率和任务结果的实际帮助。
- 用户进一步明确不衡量任务成功率、不提供人工反馈；核心只比较 MCP 与 Agent 自行检索文档的速度和检索路径效率。
- 用户最终收缩目标：不建设反馈或效果评测系统；AI 自主选择是否阅读，系统只观察推荐、实际阅读路径，以及未读/停止阅读后转向自身检索的原因。
- 用户决定 V1 暂不记录不读/停止阅读原因，避免额外工具调用和解释开销影响 Codex 执行效率；V1 只保留候选、实际读取和顺序等客观事件。

## Research Findings
- 最新 HEAD 为 `634251a fix:任务中心流程优化`，相对上一版本新增 89 个文件变更、约 7040 行，明显扩展了文档同步、本地读取、文档关系、usage cards 和 trace flow。
- 最新设计已从“prepare-first 检索”转为“read-first 文档树”：AI 从根 `AGENTS.md`/入口文档按 doc-id 逐层 `ctx read`，无法判断时才调用 `ctx prepare`。
- 数据库已从文档真源转为本地 Markdown 索引缓存；`ctx doc sync` 解析 front matter 和 Markdown 链接，正文读取/检索优先读取目标项目当前本地文件。这修复了上一版最关键的文档副本漂移方向问题。
- CLI/MCP/API 已移除 AI 手工传 traceId/reason 的要求，通过 session/current trace 自动串联 read path，并支持 `ctx reset`。接入摩擦显著降低。
- Trace UI 已改为 Entry → Document Path → Fallback Prepare → Feedback 的工作流图，更贴近用户想观察的文档阅读链路。
- 检索增加项目层级范围、入口文档保留、词频上限、id/source_path/project 信号和中文二字片段；已有 27 个业务场景覆盖 28 份 active 文档的命中验证，但尚需确认这些是排名质量测试还是仅“出现在结果中”。
- 当前根 `AGENTS.md` 仍只列开发文档索引，没有明确要求新任务先执行 `ctx read` 或调用 MCP。项目自身的 read-first 协议主要存在于受管说明和模板中，自动入口可靠性仍需核对目标项目实际 `AGENTS.md`。
- 最新实现出现一个与用户目标冲突的关键设计：read-first 在没有 prepare 时会新建任务名为“读取文档：<标题>”的 trace，因此后台不知道真实用户任务；但当前协议又把携带真实 task 的 prepare 降级为兜底。这意味着可以看“读了什么”，却不能可靠回答“某个真实任务读了什么”。
- MCP 用进程级全局变量 `CURRENT_TRACE_ID/CURRENT_DOCUMENT_ID/CURRENT_DEPTH` 串联阅读，没有 session/thread key，也没有暴露 reset 工具。如果同一个 MCP server 进程服务多个窗口或并发任务，存在跨任务串 trace 的风险；read-first 首次调用尤其容易继承上一次状态。
- CLI 虽支持 `--session`/`CTX_SESSION_ID` 保存独立状态，但默认仍使用共享 `current-session.json`；模板中的 `ctx read <doc-id>` 没带 session，可靠性依赖额外环境配置。
- 当前文档路径被实现成“上一次读取文档就是下一次读取的 parent”，只能准确表达线性路径；从根文档分别读取两个兄弟节点时，第二个可能被错误记录为第一个的子节点。
- 检索虽然增加中文 bigram 和词频上限，但仍无最低分阈值，仍会返回 score=0 的 fallback；excerpt 仍固定取正文开头 180 字符，尚未围绕命中位置生成。
- `prepare` 的 task 已改为可选，模板默认 `ctx prepare --project` 不传真实任务；这种兜底主要靠 project/area 元数据，不能证明“根据具体任务推荐准确文档”。
- 最新测试覆盖了 direct read 自动建 trace、本地正文优先、session-specific CLI state、MCP prepare/read 串联和若干中文/父子项目排序场景；但 MCP 测试显式重置模块全局变量，未覆盖两个会话并发/交错或 read-first 继承旧 trace。
- 实际目标项目 `rob_english_word_workforce/AGENTS.md` 已要求读取一张 HTTP Usage 卡片，再在 shell 中定义 `$CTX` 和 `$SESSION_ID`，之后用 CLI `ctx read --session`。这能实现链路，但新窗口需要先理解并执行多步协议，入口成本偏高，而且不是 MCP 主流程。
- 目标项目根 `AGENTS.md` 自身由 Codex 自动读取，但这次读取不会经过 Context Router；后台链路从第二层 `ctx read` 才开始，因此第一层入口只能推断、不能真实记录。
- Usage 卡要求 AI 自行生成稳定 session id；如果 AI 忘记、重复生成或不同窗口复用了同名 ID，链路会分裂或串联。系统没有将 Codex thread/session id 作为服务端一等实体。
- 目标项目文档树本身已很好地表达下一层链接和“什么时候读”，但协议通过 HTTP 获取说明→定义 shell 变量→CLI read，说明自动触发仍依赖模型遵循复杂指令，而非一个低参数 MCP tool。
- Docker Compose 后端全量测试结果为 53 passed、1 个 Starlette/httpx 弃用警告；实现与当前测试契约一致。测试完成后已停止本轮临时启动的 PostgreSQL 容器，恢复测试前无服务运行状态。
- 当前测试更偏功能正确性，尚未覆盖用户核心效果指标：新窗口触发率、任务→文档归属准确率、required-doc recall、无关阅读数、首次有效文档耗时或使用 MCP 后任务成功率变化。
- `ctx` 不是单个可删除文件：它同时存在于 `backend/src/context_router/cli.py`、`pyproject.toml` 的 console script、README/业务文档/托管文档、AI_CONTEXT_INDEX 模板、前端文档卡片命令，以及 CLI 专属测试中。
- CLI 当前承担两类职责：Agent 调用（prepare/read/trace/reset）和管理操作（project add/init-index、doc add/sync）。用户要求移除 ctx 产品方式后，前者应由 MCP 取代；后者不能简单消失，需改为后端自动同步或网页管理能力，否则文档索引无法维护。
- 当前 MCP 仍通过 `CURRENT_TRACE_ID/CURRENT_DOCUMENT_ID/CURRENT_DEPTH` 进程全局变量维持状态。MCP-only 后必须改为显式 `trace_id` 和可选 `parent_document_id` 参数，否则多窗口/并发任务仍会串链。
- 当前 `prepare_task_context` 只要求 project，task 可空且默认返回 5 篇；V1 目标应将 task 和 cwd 作为任务入口信息，候选上限收紧到 3，保证每个 trace 能对应真实任务且响应轻量。
- 当前文档读取 HTTP API 在缺少 trace 时会自动建立“读取文档：标题”的 direct-read trace；MCP-only 主链路应要求 `read_context_document` 带 `trace_id`，管理端全文预览继续使用 `untracked=true`，避免产生无法关联真实任务的孤立 trace。
- `CTX_API_URL` 仍可作为 MCP server 到后端 API 的内部配置，但不应再出现在 Agent 使用协议中；它和 `CTX_SESSION_ID/CTX_STATE_*` 的性质不同，后者属于 CLI 本地会话状态，可以随 CLI 删除。
- Usage 功能与 ctx 强耦合：后端首次访问会自动写入内置 `ctx / SESSION_ID` 卡片，前端导航、CRUD、类型和测试围绕这张卡存在。既然开发者不执行命令，V1 应移除 Usage 菜单和 API；数据库表可通过迁移删除，也可先停止使用后延迟清理，前者更彻底但会删除用户自建卡片数据。
- 当前 Trace 仍包含 feedback API、`RetrievalHit.feedback` 字段、feedback event、前端反馈控件和 Dashboard Feedback 指标。它们与已确认的 V1 范围冲突，应从交互和 API 中移除；数据库字段可暂留兼容历史数据，避免无必要的数据破坏。
- Dashboard 仍展示 CLI Entry 和 `ctx prepare` 示例，Documents 图谱与详情仍展示 `ctx read` 命令，Trace 详情仍生成 `ctx prepare` 命令；MCP-only 改造必须同步替换这些可见入口，否则产品会继续教 Agent/开发者走 ctx。
- `render_context_markdown` 的 follow-up 仍输出 `ctx read <doc-id>`。迁移后 prepare 返回必须直接携带 `trace_id` 和结构化候选，提示 Agent 使用 `read_context_document(trace_id, document_id, parent_document_id?)`，不能再返回 CLI 命令。
- 项目详情已经存在“Reload Links”网页按钮，可承接原 `ctx doc sync` 的人工兜底职责；因此 CLI 的 doc sync 可以删除，长期再补后台自动扫描，无需为了移除 ctx 同时建设复杂调度系统。
- 当前 `bin/ctx` 是三层 fallback wrapper（全局 ctx、uv、Docker Compose），可直接删除；`pyproject.toml` 同时保留 `context-router-mcp` console script，MCP 启动入口不受影响。
- 现有 MCP 配置示例仍指向默认后端 8000，而 Docker Compose 暴露 49173；正式文档需统一为实际部署地址，并将内部环境变量改为更明确的 `CONTEXT_ROUTER_API_URL`（是否重命名可作为兼容性选择）。
- OpenAI 当前 Codex 手册确认：`AGENTS.md` 会在任务前自动进入上下文，适合放简短、持久的调用规则；MCP server 配置属于 `config.toml`，可放在用户级或受信任项目的 `.codex/config.toml`。因此推荐“项目内短 AGENTS 触发规则 + 项目级 MCP 配置”，而不是让 AGENTS 解释 CLI、环境变量和 session 生成。
- Codex 手册将 MCP 定义为连接外部工具和上下文提供者的标准方式，并建议用工作流说明搭配 MCP 工具。因此本项目保留每个仓库自己的文档/AGENTS，Context Router 只做结构化检索与审计，符合工具边界。

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 按“入口触发→候选检索→摘要决策→全文读取→链路记录→效果反馈”审查 | 与用户真实目标直接对应 |
| 将 read-first 与 prepare-first 分开评价 | read-first 依赖人工文档树质量，prepare-first 依赖检索质量，优化方法和指标不同 |
| 将“真实任务 trace”设为高于“单次 read trace”的验收目标 | 用户明确要分析每个任务读了哪些文档，只有文档级 trace 不够 |
| 推荐结构化 MCP，而非继续把 CLI 作为 Codex 主入口 | 可以删除 Usage HTTP→shell 变量→CLI 的多步协议，并降低模型漏参/串 session 的概率 |
| 每个任务先创建轻量 trace，文档按需读取 | “每任务先调用”不等于“每任务强塞文档”，可返回 `no_context_needed` |
| `ctx` 仅保留为内部兼容/自动化实现，最终可删除 | 对目标用户没有产品价值，长期保留会形成第二套 agent 协议 |
| 前端承担项目接入、同步状态、效果分析和反馈 | 符合开发者只看结果、不运行命令的约束 |
| 将 MCP 触发率、文档采用率和任务效果提升分开度量 | 大量调用可能是重复/低效，未调用也可能是集成失败或任务无需文档，不能直接当作价值结论 |
| 每个任务固定一次轻量 prepare，全文读取按需 | 建立统一分母，同时避免用大量 read 调用制造虚假价值 |
| 线上指标使用行为代理，准确率使用离线带 expected-doc 的评测集 | 没有人工反馈时，真实线上任务无法知道“读到的文档是否真正确”，必须区分可观测效率与离线准确性 |
| `finish_task_context` 降为非必要 | 用户不关心任务结果，避免增加 Agent 协议负担 |
| 用 `record_context_decision` 代替任务反馈/finish | 只记录 read、skip、stop_reading、continue_source_search 及原因，满足最小观测需求 |
| 区分“正常转向源码”与“文档问题” | 文档本来不替代源码；source_is_fresher/excerpt_sufficient 不应误判为文档失败 |
| V1 删除 `record_context_decision` | 把每任务 MCP 开销限制为一次 prepare 加零到少量 read，不增加收尾协议 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| 沙箱无法访问 Docker daemon | 申请受控权限，按仓库规范使用 Docker Compose 完成测试 |
| 首次更新记录 patch 上下文不匹配 | 读取当前文件后用精确上下文更新 |
| Codex 手册首次获取因沙箱 DNS 限制失败 | 经受控网络授权重试成功，缓存中的手册为最新版本 |

## Resources
- `AGENTS.md`
- `docs/DEVELOPMENT_OUTLINE.md`
- `docs/BUSINESS_FEATURES.md`
- `docs/FRONTEND_BACKEND_FLOW.md`
- `backend/src/context_router/services/retrieval.py`
- `backend/src/context_router/services/markdown_sync.py`
- `backend/src/context_router/services/local_document_reader.py`
- `backend/src/context_router/mcp_server.py`

## Visual/Browser Findings
- 用户否决列表与详情并排、链路优先和表格抽屉三种单层布局，明确要求两级结构：外层是独立任务列表，点击任务进入独立详情，调用链路只出现在详情页。
- 用户已确认两级任务中心原型满足预期。外层只展示调用过 MCP 的任务；详情展示 `prepare_task_context`、候选文档、`read_context_document` 实际调用顺序，以及候选的已读/未读状态。
- 页面不展示未调用 MCP 的任务、不采集不读或停止阅读原因，也不要求 Agent 反馈任务成功率。
- 用户进一步确认原有 `ctx` 方式不再保留为产品入口，下一步需要梳理 CLI、Usage 卡、会话变量、文档协议、前后端页面和测试的删改范围。
