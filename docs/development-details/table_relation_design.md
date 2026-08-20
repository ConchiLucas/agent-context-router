# 表关联设计

> **当前实现状态：v1 只有查询和展示。** 关联数据的生成尚未实现——没有命名候选规则、没有跨库候选推断、没有数据实测流水线（公共字段常量除外，它已经就位）。
> 页面上看到的关联全部来自种子脚本 `backend/src/context_router/scripts/seed_table_relations.py` 写入的示例数据。
> 用户给出表名要检查并自动补全时读 [按表名补全表关联](./table_relation_complete.md)；字段对照读 [表关联种子怎么写](./table_relation_seed.md)，不要直接写投影表。
> 本文把完整设计一并沉淀，每一节都标注了「已实现」或「尚未实现」，便于后续接上真实构建流水线。
>
> **v1 只回答「方向是什么」，不回答「数据可不可信」。** 状态判定、实测指标、证据来源、命名规则、
> 阈值和行数估算这一整层**设计保留，但 v1 不落库也不展示**：迁移里没有对应的列，读取链路和页面上也没有对应的字段。
> 本文标注了「设计保留，v1 不落库不展示」的小节是给阶段三准备的，将来实现探测流水线时再把对应的列加回来。

## 1. 这个功能解决什么问题

目标库（攀枝花工作空间的 MySQL 库）没有声明任何外键约束，表之间的关系只存在于开发者的记忆和代码里。
选中一张表时，用户想直接看到：

- 这张表和别的表是一对一、一对多、多对一还是多对多，按这四类分组；
- 每一行是哪一列参与的关联，指向哪张表的哪一列；
- 哪些关系是靠中间表连起来的多对多。

**只展示判断得出来的关系。** 基数测不出来的关系（`cardinality = unknown`）一条都不上页面：
用户要的是「这两张表是什么关系」，一条答不上这个问题的行只会占位置。
没有可展示关联的表也不进入默认视图。

## 2. 数据模型（已实现）

迁移 `20260817_0036_add_workspace_table_relations.py`，在 `20260813_0035` 之后。四张表：

| 表 | 作用 |
| --- | --- |
| `workspace_table_relation_generations` | 一次生成的版本头，承载原子发布 |
| `workspace_table_relation_tables` | 该版本覆盖到的表及其四类基数计数 |
| `workspace_table_relation_edges` | 关联边，一条关系一行 |
| `workspace_table_relation_junctions` | 中间表折叠，把两条边合成一个多对多 |

### 2.1 原子发布

`generations` 按 `(workspace_id, environment, revision)` 唯一，并有两个部分唯一索引：
同一 Workspace 同一环境最多一个 `published`、最多一个 `building`。
生成流水线（尚未实现）应当在 `building` 版本下写完全部子表，再在一个事务里把旧 `published` 置为 `superseded`、把新版本置为 `published`。
读取侧只认 `published`，因此发布过程对页面不可见，也不会出现读到半份数据的情况。
子表全部对 `generation_id` 级联删除，废弃版本一行删除即可回收。

### 2.2 边的存储：规范化无向对加方向字段

一条关系只存一行，不存两个方向。两个端点按 **C 排序规则** 比较 `(database_key, schema, table, column)` 四元组，较小的一端固定放在 `left_*`：

```sql
CHECK (
  (left_database_key COLLATE "C", left_schema COLLATE "C",
   left_table COLLATE "C", left_column COLLATE "C")
  < (right_database_key COLLATE "C", right_schema COLLATE "C",
     right_table COLLATE "C", right_column COLLATE "C")
)
```

排序规则固定为 `C` 而不是数据库默认排序规则，写入方（Python 的 `<`）才能逐字节复现同样的顺序。
`pair_fingerprint` 是规范化四元组对的 SHA-256，配合 `(generation_id, pair_fingerprint)` 唯一约束，同一关系无法被写入两次。

`orientation` 记录哪一端持有被指向的键：

- `left_to_right`：左端是父（持有主键），右端是子（持有外键列）；
- `right_to_left`：右端是父，左端是子；
- `undirected`：保留值，v1 不产生。

**关键设计点：`orientation` 是结构信息，不是实测结论。** 候选生成时就知道哪一端持有外键，因此即使实测失败、`cardinality` 是 `unknown`，方向字段依然有效。
读取时靠它决定当前选中的表落在哪一侧，从而算出这一行该进哪个基数分组。

`cardinality` 始终以 **父到子** 的方向存储，取值 `one_to_one`、`one_to_many`、`many_to_one`、`many_to_many`、`unknown`。
v1 实际只写入 `one_to_one`、`one_to_many`、`unknown`；`many_to_one` 是读取时按视角翻转出来的，`many_to_many` 由 junction 在读取时合成，都不落库。
`unknown` 会被存下来但不会被展示，见 4.2。

### 2.2.1 计数列的口径

`generations` 的 `relation_count`、`hidden_count` 和
`tables` 的 `one_to_one_count`、`one_to_many_count`、`many_to_one_count`、`many_to_many_count`、`relation_count`
统计的都是**页面真正展示的行**，不是库里存了多少条边。

注意两组计数的**单位不同**：`generations` 数的是关系（边），`tables` 数的是渲染出来的行。
一条边在它两端的表上各渲染一行，所以所有表的 `relation_count` 加起来大约是边数的两倍，这不是重复计数错误。
顶部版本行要同时报这两个数时必须写明「每条在两端各算一次」，否则读者会以为对不上。

`tables` 另有一层 `folded_one_to_one_count`、`folded_one_to_many_count`、`folded_many_to_one_count`、`folded_many_to_many_count`，
记录四个计数里有几行是「已并入 `N — N` 的中间表腿」。折叠是页面级视图偏好（见 5.5），
开启时客户端把这一层从对应基数里减掉，得到的就是详情面板真正会画的行数。
分两层而不是直接存折叠后的数字，是因为两种状态都要能显示，而客户端不能从分页的表清单里自己推出哪些行可折叠。

三条 CHECK 约束把这些口径钉死：

```sql
-- generations
CHECK (edge_count = relation_count + hidden_count)
-- tables
CHECK (relation_count = one_to_one_count + one_to_many_count
                      + many_to_one_count + many_to_many_count)
-- tables：折叠只能从已有的组里减，减不出负数也减不超
CHECK (folded_one_to_one_count BETWEEN 0 AND one_to_one_count
   AND folded_one_to_many_count BETWEEN 0 AND one_to_many_count
   AND folded_many_to_one_count BETWEEN 0 AND many_to_one_count
   AND folded_many_to_many_count BETWEEN 0 AND many_to_many_count)
```

`edge_count` 仍然是库里的全部边，`hidden_count` 就是「测不出基数、不展示」的那部分。

**写入方不自己数，调 `services/table_relation_query.py` 的 `project_table_counters()`。**
它内部走的是详情面板用的同一对视图构造器（`_edge_views`、`_junction_view`），
所以左栏的计数在构造上就是详情的行数，而不是「照着同一份规则各算一遍、希望结果一致」。
这个不变量由 `tests/test_table_relation_query.py::test_every_table_counter_equals_the_rows_the_detail_draws`
遍历每张表、在折叠开和关两种状态下逐组断言。

### 2.3 状态与证据（设计保留，v1 不落库不展示）

**下面这一整层在 v1 里不存在。** 迁移里没有这些列，读取链路不返回它们，页面也不显示任何证据类文字。
本节保留下来，是为了阶段三实现探测流水线时能直接照着加回对应的列和字段。

- `state`：`confirmed` / `suspect` / `insufficient`。
- `evidence_source`：`naming`（仅命名推断）/ `probe`（有实测）。
- `naming_rule`：命中的候选规则名。
- `probe_status`：`ok`、`empty`、`all_null`、`small_sample`、`timeout`、`rejected`、`skipped`、`error`。
- 实测指标：`child_keys`、`matched_keys`、`match_ratio`、`sampled_rows`、`max_per_parent`、`sample_truncated`、`probed_at`。
- `generations.confirm_floor` 和 `suspect_ceiling` 记录该版本使用的阈值，历史版本不会被后来改动的阈值重新解释。
- `generations` 的 `confirmed_count`、`dirty_count`、`probed_count`、`candidate_count`、`skipped_candidate_count`、
  `naming_ruleset_version`、`probe_statements_used`、`probe_statements_budget` 同属这一层。
- `tables` 的 `estimated_rows`、`has_soft_delete`、`primary_key_columns` 也一并推迟：页面不读，留着只会逼写入方编造值。

**两档 suspect 不需要额外字段。** 命中率低于 `suspect_ceiling` 时关系本身可疑，`cardinality` 写 `unknown`，这一档不展示；
命中率介于 `suspect_ceiling` 和 `confirm_floor` 之间时关系成立、只是数据脏，`cardinality` 保留实测方向，这一档要展示。
所以两档靠 `cardinality` 是否为 `unknown` 就能分开，没有冗余列：
低档随「基数未知」一起被过滤，中档进它真正的基数分组。这条设计不依赖 `state` 列存在，
落到 v1 就是：能测出方向的进分组，测不出的整条不展示。

**小样本降级用 `probe_status` 表达。** 它是这条边的实测结果，放在边上语义最干净：
`state = 'insufficient'`、`probe_status = 'small_sample'`、`cardinality = 'unknown'`，因此同样不展示。

### 2.4 中间表折叠

`junctions` 指向两条边，两条边的子端都是同一张中间表。两个父端就是多对多的两侧。
搭配是否重复（`pair_unique`、`junction_rows`、`distinct_pairs`）属于 2.3 那一层，同样设计保留、v1 不落库不展示。

## 3. 判定规则

### 3.1 公共字段排除（常量已实现）

这一组记账列完全不参与关联，页面上不出现，也不为它们生成任何说明：

```
deleted, tenancy, company_id, creator, create_time, modifier, modify_time
```

常量定义在 `backend/src/context_router/services/table_relation_rules.py` 的 `COMMON_COLUMNS`，
种子脚本和将来的构建流水线都从这里取，不各自抄一份。

**按精确列名匹配，不用前缀或子串匹配。** `company_id` 排除，`affiliation_company_id` 是一条正常的外键、不属于这一组。
匹配忽略大小写（`casefold`），但比较的始终是整个列名。`is_common_column` 有单元测试守着这条边界。

### 3.2 候选生成（尚未实现）

原设计的 R1–R8 命名候选规则（后缀 `_id` 剥离、表名公共前缀剥离、复数处理、自引用、库前缀推断、跨库候选等）**已从 v1 移出**，
**v1 没有任何代码实现它们**。
需要注意的已知漏检：`cs_dsly_declaration_order_cargo.declaration_id` 这类「列名去掉 `_id` 后匹配不上父表名」的关系，纯命名规则覆盖不到。

### 3.3 实测与阈值（设计保留，尚未实现，相关列 v1 不落库）

- `match_ratio >= confirm_floor`（0.9）：`confirmed`，按 `max_per_parent` 定 `one_to_one`（=1）或 `one_to_many`（>1）。
- `suspect_ceiling`（0.5）`<= match_ratio < confirm_floor`：`suspect`，保留方向。
- `match_ratio < suspect_ceiling`：`suspect`，`cardinality = unknown`。
- `child_keys == 1` 或 `sampled_rows < 5`：`insufficient` + `small_sample`，即使命中率是 100%。
- 子表无行：`insufficient` + `empty`；整列为 NULL：`insufficient` + `all_null`。
- 跨库候选：不建立跨库连接比对数据，`evidence_source = 'naming'`、`probe_status = 'skipped'`、`cross_database = true`，页面标「未验证 · 跨库」。

实测查询必须复用既有只读链路（`ConnectorManager`、`SqlSafetyPolicy`、`database/policy.py` 的 fail-closed 校验和有界查询限制），
不得绕过安全与限流机制；大表上的 `COUNT`/`GROUP BY` 需要采样、超时和行数上限，失败一律降级为「证据不足」而不是猜测。

## 4. 读取链路（已实现）

```
api/table_relations.py  ->  services/table_relation_query.py  ->  repositories/table_relation_repository.py
```

### 4.1 视角翻转

存储是方向中立的，页面是「以当前选中的表为主语」的。`services/table_relation_query.py` 负责这个转换：

- 选中的表是 **父端**：`direction = inbound`（别人指向我），基数直接用存储值。
- 选中的表是 **子端**：`direction = outbound`（我指向别人），基数按 `one_to_many <-> many_to_one` 翻转，`one_to_one` 翻转后不变。

翻转之后的基数就是相对当前表说的，所以它同时充当分组依据：`1 — N` 是「一条本表记录对应多条对方记录」，
`N — 1` 是「多条本表记录指向同一条对方记录」。方向信息因此不需要额外的分组维度承载，
但每一行仍然带 `direction` 字段，供前端决定列名那一行的箭头朝向。

自引用（`sys_menu.parent_id -> sys_menu.id`）父端和子端是同一张表，因此**同一条边同时落在两个基数分组里**：
`1 — N` 是「一个父节点下有多个子菜单」，`N — 1` 是「多个菜单共享一个父节点」。这是正确的，不是重复。

### 4.2 只展示判断得出来的关系

`cardinality = unknown` 的边一律不进任何分组。将来接上探测流水线后，被挡在外面的会包括证据不足的全部情形
（`all_null`、`empty`、`small_sample`、`timeout`、`rejected`、`error`）、跨库未验证的候选，以及 suspect 低档。

suspect 中间档（命中率介于 `suspect_ceiling` 和 `confirm_floor` 之间）**保留**：方向是测出来的，只是数据脏。
它进自己真实的基数分组，徽章显示真实基数。v1 页面不区分数据干净与否，因此这一档和 confirmed 在页面上完全一样。

**过滤放在查询服务，不放在前端。** 左栏每张表的四个计数是存在 `tables` 表里的，
如果过滤发生在前端，那些计数就会把不展示的边也算进去，页面会出现「左栏说有 1 条、点进去一条都没有」。
把规则收在服务端一处，`services/table_relation_rules.py` 同时供读取路径和写入方（种子脚本）使用，
计数和渲染出的行就不可能对不上。代价是只读接口不再返回 unknown 的边；
`detail.hidden_count` 仍然报出被挡掉了几条，测试用它证明过滤真的发生了。

### 4.3 分组与排序

- 四个分组固定顺序：`one_to_one`、`one_to_many`、`many_to_one`、`many_to_many`。
- 空分组不返回，四组全空时 `groups` 是空数组。
- 组内排序：先对方表全名（`database_key.schema.table`），再本表列名，最后对方列名。
  **只用行上的标识信息**，重建时任何用户看不见的变化都不会让行的位置跳动；将来加回实测指标也不得掺进排序键。
- junction 全部归入 `many_to_many` 组，按对方表全名再中间表全名排序；普通边不会出现在这一组。
- 列名不再是一层分组，改为每行行内的 `self_column → counterpart.column` 标签。
  同一列的多条关系可能落在不同的基数组里，这是正常的。

### 4.4 折叠标记

服务端只**标记**不过滤：一行的对方表正好是本表参与的某个 junction 的中间表时，`folded_into_junction = true`。
前端据此隐藏或恢复，开关是纯客户端操作，不需要重新请求。折叠后某一组一行不剩时，整组不渲染。
从中间表自己的视角看，junction 不返回（它只有两条指向外侧的边），避免自己和自己形成多对多。
两条腿里只要有一条基数未知，整个 junction 也不返回——捷径不可能比它依赖的两条边更可信。

被折叠的行按定义是「本表作为父端、子端是中间表」的那条边，
它的基数就是入库的父到子基数，所以理论上四类都可能，`folded_*_count` 因此也是四个而不是一个。
标记按**表**匹配而不是按边 id 匹配：本表如果有两列都指向同一张中间表，两行都会被折叠，
`project_table_counters()` 走的是同一套 `_edge_views`，所以计数会跟着一起算对。

同一条边在中间表那一端是一条普通的 `N — 1`，**不会**被折叠：折叠只隐藏外侧表上那条与多对多重复的说法。
所以 `sys_user_role` 的两条 `N — 1` 在两种折叠状态下都在。

### 4.5 六个只读 GET 接口

| 路由 | 用途 |
| --- | --- |
| `GET /api/workspaces/{id}/table-relations/status` | 当前版本、展示口径的统计、库别名清单、示例数据写入命令 |
| `GET /api/workspaces/{id}/table-relations/tables` | 表清单，支持 `only_related`、`database_key`、`search` |
| `GET /api/workspaces/{id}/table-relations/table` | 单表详情，扁平关系列表（表身份走查询参数，避免路径转义） |
| `GET /api/workspaces/{id}/table-relations/table/writes` | 单表插入入口，按当前选中表返回插入调用；空列表表示还没录入 |
| `GET /api/workspaces/{id}/table-relations/table/updates` | 单表更新入口，按当前选中表返回更新调用；空列表表示还没录入 |
| `GET /api/workspaces/{id}/table-relations/relation` | 单条关系的代码点位与体检项 |

**没有 rebuild POST 接口。** 没有构建流水线就不需要它，因此 `browser-api-policy.ts` 和 `middleware/browser_read_only.py` 都不需要改动，
`task_repository` 的系统任务过滤也不需要新增探测任务类型。空状态卡片直接给出种子脚本命令，让用户知道怎么手动造数据。

## 5. 界面规格（已实现）

### 5.1 组件拆分

| 组件 | 职责 |
| --- | --- |
| `table-relation-explorer.tsx` | 容器：工作空间选择、拉数据、加载/错误/空状态 |
| `table-relation-table-list.tsx` | 左栏：搜索、「只看有关联的表」开关、折叠开关、表条目 |
| `table-relation-detail.tsx` | 中栏：表头、插入入口/更新入口按钮、关系列表 |
| `table-relation-write-modal.tsx` | 当前表的插入或更新入口弹层 |
| `table-relation-group.tsx` | 分组外框：标题、计数、可选操作区 |
| `table-relation-edge-row.tsx` | 单行关系与单行多对多 |
| `table-relation-badge.tsx` | 基数徽章 |

呈现逻辑（徽章、列名对、排序、折叠过滤、分组、计数）全部放在 `lib/table-relations.ts` 的纯函数里，
由 `lib/table-relations.test.ts` 覆盖。仓库前端测试只跑 `lib/*.test.ts`，没有组件渲染环境，所以可测逻辑必须留在 `lib/`。

### 5.2 四个分组

固定这个顺序，分组头只有徽章字形和行数计数，没有说明文字：

| 顺序 | 标题 |
| --- | --- |
| 1 | `1 — 1` |
| 2 | `1 — N` |
| 3 | `N — 1` |
| 4 | `N — N` |

每组为空整组不渲染，不留空标题；四组全空时显示「这张表没有可展示的关联」。
四类的中文含义由徽章的 `aria-label` 承载（见 5.3），不再在分组头上重复一遍。

### 5.3 基数徽章

徽章只说基数，不兼职表达状态，因此只有四种字形。
不靠颜色区分：字形本身携带方向，`aria-label` 念出中文含义。
**`aria-label` 不能删。** 白话句去掉之后，它是屏幕阅读器唯一能听到的方向说明。

| 情况 | 字形 | 无障碍标签 |
| --- | --- | --- |
| 一对一 | `1 — 1` | 一对一 |
| 一对多 | `1 — N` | 一对多 |
| 多对一 | `N — 1` | 多对一 |
| 多对多 | `N — N` | 多对多 |

绿色（`--accent`）只用于选中和焦点。

### 5.4 每行的内容

**一行只有两层，页面只回答「方向是什么」。**

1. **基数徽章**：`1 — N` 这样的字形，`aria-label` 念出中文。
2. **列名行**：`self_column`、方向箭头、`对方表.对方列`。分组不再按列切分，列名由这一行承载。
   跨库时对方表带库别名前缀。

渲染出来就是 `1 — N    id  ←  sys_menu.parent_id` 这一行。

白话主语句、状态标签、证据 chips、实测时间**全部不展示**，对应的字段也不落库（见 2.3）。
唯一的例外是折叠开关**关闭**时那行 `已并入 N — N`：它不是证据文字，
而是解释这一行为什么和同一张表的 `N — N` 说的是同一件事，所以必须留着。

详情表头只有表名和 `库别名.schema`（跨库时用它区分），没有行数、主键和逻辑删除标识。
顶部版本行保留「第 N 版 · 环境 · 左栏合计 N 处关联展示（来自 N 条关系，每条在两端各算一次） · 数据写入于 …」，
不带任何按状态分的计数。

### 5.5 折叠开关是页面级视图偏好

**开关放在左栏，和「只看有关联的表」并列，不放在详情表头。** 理由：

1. 它同时决定左栏**每一张**表卡片的计数和右侧详情画哪些行。放在详情表头会暗示「只作用于当前选中的表」，
   而这正是它作为局部开关时产生的 bug——左栏读库里的原始计数、不跟随折叠，于是
   `sys_user` 卡片写 `1 — N 2`、点进去只有 1 条。控件的位置必须说真话。
2. 在详情表头它只在当前表有可折叠行时才出现，但它对别的表的计数依然生效。
   一个「看不见却仍在起作用」的控件比一个一直可见的更糟。
3. 放在它所影响的列表上方，改动和被改动的数字在同一屏内，用户能直接看到因果。

开关仍然只在整页确实有可折叠行时出现（`foldableRowCount(tables) > 0`），标签写明全页折叠了几条以及影响范围。
它是纯客户端状态，切换不触发任何请求。

### 5.6 计数跟随折叠

左栏卡片显示 `基数计数 - 折叠计数`，因此：

- 某一组减到 0 时，这个基数标记**整个消失**，不显示 `1 — N 0`。
- 一张表四组全部减到 0 时，它按「没有可展示的关联」处理：`只看有关联的表` 开启时从左栏消失，
  「已隐藏 N 张」跟着变。种子数据里触发不到这一条（能折叠说明这张表参与了 junction，
  而 junction 本身就是它的一条 `N — N`，所以减不到 0），但 schema 不禁止，前端照样要算对，测试用构造数据覆盖。
- 排序也按折叠后的计数排，否则折叠会把一张没有可见行的表排在有好几行的表前面。
- 顶部版本行的总数由左栏计数逐表相加得到，所以它必然跟着开关变，用户把卡片上的数字加一遍就能核对。
  这个数和 `generations.relation_count` 单位不同（见 2.2.1），文案里写明「每条在两端各算一次」。

### 5.7 其他规则

- 左栏每张表的计数按四类基数显示（`1 — 1 1`、`1 — N 2` 这样），口径与详情分组一致；没有可展示关联时显示「没有可展示的关联」。
- 左栏默认「只看有关联的表」，并说明隐藏了多少张没有可展示关联的表。
- 响应式：1080px 以下左右栏堆叠、表清单限高；720px 以下徽章与正文改为上下排列。
- 无障碍：分组用 `aria-labelledby`，徽章用 `role="img"` 加中文标签，选中项带 `aria-current`，焦点沿用全局 `:focus-visible` 样式。

## 6. 示例数据（已实现）

`backend/src/context_router/scripts/seed_table_relations.py` 可重复执行，按 `(workspace_id, environment)` 覆盖式重写：

```bash
docker compose exec backend uv run python -m context_router.scripts.seed_table_relations \
  --workspace <workspace_id>
```

脚本以「父端、子端」的人类读法声明每条关系，规范化左右端和 `orientation` 由代码推导，
声明里不需要知道哪一端排序在前。同一份声明同时供数据库写入和查询层测试使用（`build_seed_projection` / `load_into_memory`），
因此测试断言的就是页面上真实展示的那批数据。
每张表的八个计数由 `project_table_counters()` 从脚本已经构造好的边和 junction 记录里数出来，
走的是详情面板用的同一对视图构造器，不是照着声明另算一遍。
脚本还会拒绝任何用到公共字段的声明，以及任何有关联但没登记进 `SEED_TABLES` 的表。

每条声明只有父端、子端、基数和是否跨库四项，因为页面只展示这些；
声明里没有实测指标可填，也就不需要为不展示的字段编造数字。

### 6.1 12 条边里有 5 条故意不展示

`org_id`、`position_id`、空表的 `declaration_id`、`dict_id`、
跨库的 `affiliation_company_id` 这五条边基数是 `unknown`，都留在库里，不从种子里删掉。它们是过滤规则的回归夹具：
查询层测试逐条断言这些边**能从存储里读出来、但不出现在任何分组里**，
删掉它们就等于把这条规则的唯一守卫也删掉了。将来真实流水线也会产出这类边，留着让示例数据保持真实。

### 6.2 `sys_user` 覆盖全部四组

用户主要看的这一页四组齐全：

| 组 | 示例 |
| --- | --- |
| `1 — 1` | `sys_user_ext.user_id → sys_user.id`，每个用户一条扩展记录 |
| `1 — N` | `sys_user_role.user_id`、`sys_operation_log.user_id` 指向 `sys_user.id` |
| `N — 1` | `sys_user.tenant_id → sys_tenant.id` |
| `N — N` | `sys_user` 经 `sys_user_role` 到 `sys_role` |

`sys_menu` 覆盖自引用同时落在 `1 — N` 和 `N — 1`。
`sys_login_log`、`cs_dsly_config` 没有任何边；`sys_organization`、`sys_position`、`sys_dict`、`sys_dict_item`、
`sys_company`、`cs_dsly_declaration_order`、`cs_dsly_declaration_order_cargo` 只有不展示的边，
两种情况在页面上都表现为「没有可展示的关联」，会被左栏开关隐藏。

### 6.3 折叠开关的示例

`sys_user_role` 这个 junction 让两张外侧表各有一条可折叠的腿，全页共 2 条：

| 表 | 折叠关 | 折叠开 |
| --- | --- | --- |
| `sys_user` | `1 — 1 1`、`1 — N 2`、`N — 1 1`、`N — N 1`，合计 5 | `1 — 1 1`、`1 — N 1`、`N — 1 1`、`N — N 1`，合计 4 |
| `sys_role` | `1 — N 1`、`N — N 1`，合计 2 | `N — N 1`，合计 1（`1 — N` 标记整个消失） |
| `sys_user_role` | `N — 1 2` | `N — 1 2`（中间表那一端不折叠） |
| 全页合计 | 16 处 | 14 处 |

`sys_user` 是「组还剩一行」的例子，`sys_role` 是「组减到 0、标记消失」的例子。

## 7. 分阶段落地顺序

| 阶段 | 内容 | 结束时用户能看到什么 |
| --- | --- | --- |
| 一（已完成） | 四张表迁移、只读读取链路、三个 GET、完整前端、种子示例数据 | 页面可以点开每张表，按四类基数看到它的全部关系 |
| 二（尚未实现） | 命名候选规则（公共字段常量已就位） | 真实候选边替换种子数据 |
| 三（尚未实现） | UAT 只读实测与基数裁决，同时按 2.3 加回状态与证据列 | 关系带上真实命中率和基数，两档 suspect 自然产生 |
| 四（尚未实现） | 生成流水线的任务化与原子发布 | 可重复重建，页面显示上次实测时间 |

## 8. 与既有约定的关系

- 分层与命名跟随 `data_sources`、`database_environments`：`api/` 只做参数校验和错误映射，`services/` 放转换逻辑，`repositories/` 提供 Protocol 加 InMemory 加 Postgres 三份实现。
- `services/table_relation_rules.py` 是读写双方共用的规则源：公共字段名单、可展示基数、基数翻转。任何新的写入方都必须从这里取，不要另抄一份。
- 迁移、测试、lint、build 全部通过 Docker Compose 执行；改后端代码后 `docker compose restart backend`。
- 阶段二及以后接入实测时，必须复用既有只读数据库访问链路，不得新开绕过 `SqlSafetyPolicy` 的通道。

## MCP 工具 `read_table_relations` 与 `search_relation_tables`

表关联三块内容（关系列表、插入入口、更新入口）通过 MCP 暴露给 agent，一查一读两个工具，实现分工：

- `services/table_relation_context.py`：task 作用域投影。`read` 入参 `task_id` + `tables`（1~10 个裸表名，批量；同名多库时补 `database`）+ 可选 `sections`（`relations`/`writes`/`updates`，缺省全取）+ `include_evidence`。返回顶层带 `workspace_root`，其下所有 `file` 都是相对它的路径。从 task 解析 workspace 与环境，不接受 workspace_id；表名先做子串检索再精确匹配。单个表名解析失败（查无此表、同名歧义）落为该条目的 `table_request` + `error`，不影响同批其他表；无已发布数据仍整体报错。
- `search` 入参 `task_id` + 可选 `query`（子串）、`database`、`only_related`（默认 true）、`limit`。返回按 relation_count 降序的表清单和 total/related/returned 三个计数，用于业务词→确切表名的解析。工具描述写明：查不到只说明快照里没有，表本身是否存在要问 `search_database_objects`。
- `include_evidence=true` 时每条关系附 `evidence`：两维结论（`code_cardinality`/`code_evidence`/`db_cardinality`/`db_evidence`）、六个实测数字、可重跑的体检 SQL（agent 可直接投给 `execute_database_query` 用当下数据复核）、以及边上的代码点位（`class`/`method`/`kind`/`implies`/`file`，implies 已按视角翻转）。
- 关系行只给一个 `cardinality`，取代码侧结论——它说明写入路径允许什么，正是调用方要面对的问题；数据侧只说明某次快照里恰好有什么。两维不一致或代码侧不可测时加 `uncertain: true`，不解释原因：两维为什么不一致是数据质量问题，页面上看得到，agent 无法据此决策，把四个 key 摊到每一行不值得。想要拆解就开 `include_evidence`。方向用 `role`（child/parent/self）表述。
- 入口按文件归并：每组给 `class`、`file`（Workspace 相对路径）、`methods`（`name` + `kind`）。同一个 service 常有多个方法写同一张表，逐方法重复一遍完整路径是这个返回体里最大的一块；根路径改为整个响应只给一次 `workspace_root`，由 agent 拼接。`kind` 保留在方法级而没有上提到组级，因为同一个类里 `batch_insert` 和 `update` 可以并存。故意不返回行号与 snippet：类名 + 方法名能扛住挪动代码的改动，行号在失效之后仍然看起来很精确。
- 精简前后（`cs_bt_departure_plan`，14 条关系 / 14 个入口，紧凑序列化）：关系段 2380 → 1910，入口段 3947 → 2050，合计省 37%。
- `mcp_server.py` 注册两个工具与 trace 摘要；`mcp_contract.py` 的 `CONTEXT_ROUTER_TABLE_RELATION_TOOL_NAMES` 进入追踪白名单；`main.py` 注入 `TableRelationContextService`；`mcp_integration.py` 的接入页工具清单同步。
- 语义约束写死在工具描述里：`writes`/`updates` 为空只代表未登记入口，不代表没人写这张表；结构查询归 `search_database_objects`，关系与写入口归本工具。
- 测试：`tests/test_table_relation_context.py`（种子数据投影 + MCP 转发/禁用），并同步更新了 `test_mcp_server.py`、`test_mcp_integration_api.py` 的工具清单断言。
