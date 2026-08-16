# SQL 表关联索引

## 第一版边界

- 只采集后端项目中的 `.sql` 文件，不分析 Java、Go 或 Python 调用图。
- 只保存 SQL AST 中 `JOIN ... ON/USING` 明确出现的跨表字段等值条件；关系固定为无方向 `observed_join`。
- 每个 `SELECT/UPDATE/DELETE` 使用独立的表别名作用域；嵌套查询和 `UNION` 分支会分别分析其内部物理表 JOIN，不跨作用域复用或猜测别名。外层通过派生表别名连接子查询结果时仍失败关闭。
- JOIN 条件先按顶层 `AND` 拆分。包含 `OR` 的局部分组单独跳过；仅当分组内存在跨表字段条件时记录诊断，单表字段与常量的 OR 静默忽略。同级不含 `OR` 的直接字段等值条件继续采集；不会从 OR 分支中抽取可选等值条件。
- 表和字段必须在对应只读数据库元数据中唯一存在，否则跳过，不猜测。诊断会把动态模板、表或字段无法唯一确认、别名无法确认或存在歧义留在“需要处理”。“CTE/派生表”“复杂 OR”“非等值”“相关子查询”视为正常忽略，出现在系统分类「解析器暂不支持」中，文件继续扫描。“默认数据库缺表 / 缺字段”和“语句错误”（未限定别名、循环模板、仅 WHERE 跨表等值）进入「没有分析价值」，视为正常忽略，下次扫描整文件跳过。只有迁移/DDL 等已证明不应建立运行时关系的情况也归为正常忽略。不能用一个宽泛原因混合统计。同一条 JOIN 两侧存在不同元数据问题时按字段分别记录，提示包含默认数据库、物理表、字段和 SQL 表达式。
- 未配置工作空间预处理 Profile 时，`<<...>>` 动态模板块本身不参与分析；移除模板块后只解析块外静态 SQL，并记录 warning。
- 工作空间可通过 `deploy/context-router/sql-preprocessors.yaml` 选择内置安全处理器，并按项目、SQL 路径和方言匹配；配置不执行任意代码或任意正则替换。
- 模板注释、明确包装器、条件分支和值占位符可生成有界候选；Workspace Profile 可排除迁移/DDL 路径，排除记录以 `migration_sql_ignored` 进入“安全跳过”，不伪装成运行时 SQL 解析失败。
- 连续 FreeMarker 条件可使用 `baseline_and_single` 生成“基础候选 + 单分支候选”，避免无业务语义的笛卡尔组合；`if/elseif/else`（兼容项目中的 `elseIf` 大小写写法）按互斥分支生成候选，绝不把多个分支拼接为一条 SQL。`<<...>>` 可选择保留条件体。值占位符在 strict 模式下只替换可证明的值位置，结构表达式继续失败关闭。
- 循环模板、动态表名、动态字段名、未知指令和未闭合块失败关闭；所有候选都无法形成有效 SQL 时额外记录 `source_sql_invalid`，用于定位业务 SQL 或 Profile 规则问题。
- 不声明外键、上下游、主从、所有权、血缘或业务依赖。
- MCP 按精确表名返回直接一跳关系。每个可用后端项目单独配置一个 Workspace 表关联默认数据库，工具不读取 task 的 LOCAL/TEST/UAT 环境；只有这些默认库之间仍存在同名表时，才需要使用 `database_key/schema` 消除歧义。数据库对象搜索和只读 SQL 仍严格按 task 环境访问真实数据。
- MCP 参数固定使用单数 `table`。`detail_level` 支持 `compact/evidence/full`：默认 `evidence` 返回路径、关联表达式和必要模板标记但不返回完整 SQL；`compact` 不返回证据；`full` 才返回完整规范化 SQL、Profile 哈希和候选 ID。页面查看接口继续使用 `full`。
- MCP 默认每页返回 20 条关系、每条关系 5 份证据；`relation_limit/relation_offset` 支持稳定翻页，`evidence_limit_per_join` 可在 1 至 20 间调整。响应始终返回关系总数、返回数、`has_more/next_offset`，每条关系也返回证据总数、返回数和截断标记，禁止无提示截断。页面查看接口不使用 MCP 分页预算。
- 页面表清单接口按稳定排序提供 `total/limit/offset/has_more/next_offset`，单页最多 200 张表；前端自动读取并合并全部页面，不允许以固定切片静默遗漏后续表。
- 页面不展示 TEST/UAT 选择器，状态、表清单、诊断和关系图统一使用表关联默认数据库。页面明确显示默认数据库配置数量；配置不完整时禁止刷新。默认库配置使用独立 revision，修改后旧构建批次立即失效，完成新一轮刷新后才重新对页面和 MCP 可见。
- 扫描前先应用两层白名单。系统分类外层分为「没有分析价值」和「解析器暂不支持」。前者自动排除纯 DDL、无 JOIN 的单物理表查询、不包含查询、JOIN、子查询或第二张表的纯 INSERT/UPDATE、无关联初始化脚本，上一轮已确认默认数据库缺表或缺关联字段的 SQL，以及未限定别名、循环模板或仅 WHERE 跨表等值等无法安全分析的 SQL。后者只分类查看复杂 SQL、CTE/派生表、复杂 OR、非等值和相关子查询，文件仍进入解析；无法解析或无法确定语句形态时失败关闭，继续正常扫描。每个 SQL 文件只进入一个系统分类 tab：先按语句形态归入 DDL/单表/纯写入/初始化，再按缺表缺字段、语句错误，再按更具体的解析器缺口，最后才落到复杂 SQL。项目更新把该归属写入当前 generation 快照；白名单列表只读快照，点开文件才读取原文。白名单查看窗口可按系统规则列出命中的项目 SQL 文件，并按需展示其原文。项目白名单保存在 `table_relation_sql_whitelist`，只接受精确 `.sql` 相对路径；命中后整个文件不产生关系或诊断。

## 借鉴点

| 参考项目 | 本项目采用的逻辑 | 未采用的部分 |
| --- | --- | --- |
| ArchGuard | `SqlFileCollector` 与 `SqlObservedJoinAnalyzer` 分离，未来 Go/Python/Java 可增加独立 Collector | 不复制其完整架构治理模型 |
| SQLLineage | 使用 SQL AST 而非正则建立结构事实；无法解析时失败关闭 | 不把等值 JOIN 自动解释成 lineage |
| OpenMetadata | 关系携带 SQL 文件、表达式和语句证据；页面从表节点进入证据 | 不采用其服务端、实体模型或方向语义 |
| jQAssistant | 先持久化观察事实，再由查询/MCP 投影；事实层不混入业务推断 | 第一版不增加可配置规则语言 |
| Joern | 第一版不借鉴 | 跨语言代码属性图留到 SQL 版准确率稳定后评估 |

## 数据与发布

一次刷新按 `workspace + project + database_key` 建立 generation。关系、字段对、证据和系统分类文件快照在同一事务中替换，完成后 build 才变为 `ready`。失败目标保持 `failed`，不会暴露它的旧关系；同一 Workspace 同时存在成功和失败目标时状态为 `partial`，查询只读取成功目标。旧批次的 `automatic_file_count` 为空时，系统分类列表仍按现场扫描回退。

`partial` 状态可只重建失败目标，避免重复扫描已就绪目标。元数据读取只对连接中断和超时执行两次有界重试；语法、权限和 Profile 错误不重试。MySQL 协议目标会通过版本与 `version_comment` 识别 Doris；Doris 目录读取不发送其不支持的 `START TRANSACTION READ ONLY`，并只使用已验证兼容的表/字段元数据查询。

页面的项目更新按钮是唯一重建入口；第一版不监听源码变化。进入页面时项目下拉默认“全部项目”。SQL 白名单从同一区域进入：系统白名单可按全部项目筛选查看，项目路径白名单仍按单个项目保存，保存后自动重建该项目。SQL、白名单或数据库结构变化后必须完成对应更新，MCP 才能看到新 generation。

解析器跳过的候选不会只保存为截断字符串。`table_relation_warnings` 按当前构建 generation 保存项目、数据库别名、SQL 路径、稳定原因码、相关表达式和归并次数；页面可按原因或关键词查询，并把原因投影为“源码错误 / 预处理边界 / 元数据未确认 / 关系能力缺口 / 安全跳过”五类。凡可能存在关系但当前未采集的诊断均进入待处理；只有迁移/DDL 等明确无须建立运行时关系的诊断进入正常忽略。旧 generation 的 `join_column_unresolved` 与 `join_metadata_unresolved` 只为历史兼容保留，新扫描必须写入表/字段级细分原因码。新的 generation 发布或失败时会原子替换该目标的诊断，查询不会混入旧批次。状态中的 `warning_count` 是完整出现次数，`warnings` 只保留少量兼容预览。

模板派生证据在 `table_join_evidences` 保存 `preprocess_profile_id`、Profile 内容哈希、候选 ID、按顺序应用的规则和 `template_derived`。MCP 与页面据此明确区分原生标准 SQL 和模板候选；证据中的 SQL 是实际送入 AST 的规范化候选，原始内容仍以只读工作空间中的 `source_path` 为准。Profile 缺失时不改变旧行为；Profile 文件无效时整个 Workspace 刷新在创建新 generation 前失败，保留既有索引。

## 验证

专项用例位于 `backend/tests/test_sql_observed_table_relations.py`，覆盖：

- 普通、复合等值 JOIN 和 `JOIN USING`；
- 项目 `<<...>>` 模板块外静态 JOIN；
- 系统分类覆盖「没有分析价值」的整文件跳过，以及「解析器暂不支持」的只读查看；项目路径白名单覆盖保存、校验和扫描前排除；工作空间级系统白名单可汇总已配置项目，并用 `project_id` 区分同名路径；项目更新后的系统分类列表读 generation 快照，不再每次重新扫描全部 SQL；
- 纯 OR 分组、非等值、CROSS JOIN、无表限定字段和不存在字段不建边；带 OR 的复合条件只保留同级顶层 AND 中可独立确认的等值条件；
- 一跳无向返回、字段对和 SQL 证据；
- failed 批次失败关闭、partial 只返回 ready 目标；
- FastMCP 工具参数转发与返回语义在 `test_mcp_server.py` 中验证。
- `test_mcp_server.py` 还锁定 `tools/list` 只能声明单数 `table`、三档 `detail_level` 及默认 `evidence`，防止工具清单和运行校验再次漂移。
- 服务测试覆盖稳定关系分页、最后一页、证据上限以及 `compact` 主动省略证据时的显式截断标记。
- `backend/tests/test_table_relation_task_environment.py` 覆盖 LOCAL/TEST、UAT 自动消歧、逻辑数据库别名、跨环境拒绝和环境版本变化失败关闭。
- `backend/tests/fixtures/sql_table_relation_golden.json` 固定 34 条人工可读 SQL 黄金样本，覆盖普通/复合/多表 JOIN、`USING`、模板、UPDATE/DELETE JOIN、括号、大小写、嵌套 `UNION` 别名隔离，以及 OR 局部分组、单表常量 OR 降噪、跨表非等值、单表算术过滤降噪、未知字段、派生表、动态空 SQL、WHERE 跨表等值等失败关闭边界。
- `backend/tests/test_sql_preprocessing.py` 覆盖工作空间 Profile 选择、注释/包装器/值占位符、条件分支、循环阻断、动态标识符阻断、未知/未闭合模板以及模板证据审计。

按仓库规范执行：

```bash
docker compose exec backend uv run --extra dev pytest -q
docker compose exec frontend npm test
docker compose exec frontend npm run build
```
