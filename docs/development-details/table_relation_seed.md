# 表关联种子怎么写

用户只给表名、要检查并自动补全时，先读并执行
[按表名补全表关联](./table_relation_complete.md)。本文是字段和枚举对照，不是那份操作流程。

页面上的关系列表、关系详情、表级插入入口和更新入口都不是自动扫出来的，也没有录入界面。
四份数据都写在同一个种子文件里，任意 AI 按本手册补一行再跑脚本即可。脚本按
`(workspace_id, environment)` **整版覆盖**，可以反复执行。

唯一写入入口：

`backend/src/context_router/scripts/seed_table_relations.py`

不要直接 INSERT PostgreSQL 的 `workspace_table_relation_*` 表。那样会绕过
`check_sites` / `check_write_site` / `check_update_site` / `check_counts`，下次种子一跑又被覆盖。

## 四份数据互不推导

| 页面 | 种子里写什么 | 回答什么 |
| --- | --- | --- |
| 左栏表清单 + 中栏关系行 | `SEED_TABLES` + `SEED_EDGES`（含 `measured`） | 这张表和谁有关，代码/数据库各判成什么基数 |
| 点开一行的关系详情 | 同一条 `SEED_EDGES` 上的 `sites` | 这条外键为什么是 1:1 或 1:N；体检项 SQL 由端点现算，不用手写 |
| 表头「插入入口」 | `SEED_WRITES` | 哪些方法在向**这张表插入行** |
| 表头「更新入口」 | `SEED_UPDATES` | 哪些方法在更新**这张表已有的行** |

关系点位挂在边上，插入/更新入口挂在表上。同一段 Java 可以三边都出现，那不是重复：
一边说父键怎么来，一边说哪次调用插入，一边说哪次调用更新。

不要把边上的 `sites` 聚合成表级插入或更新入口。货物的 `batchInsert` 填了四个外键，
按边聚合会列四次；派车单作为父表时还会把货物插入显示成「写入派车单」。
插入列表和更新列表也不互相推导：同一方法既可以插入再更新，两边各记一条。

## 可以并行，按表认领

多个 AI 同时补数据时，一次只认领一张表（或一个明确的边集合），在对应 tuple
**末尾追加**，不要改别人已经写好的条目，除非那条本身是错的。

建议顺序：

1. 关系列表：`SEED_TABLES` 登记表，`SEED_EDGES` 加边和实测。没有边，列表和详情都空。
2. 关系详情点位：给已有边补 `sites`，并让代码结论和点位相符。
3. 表级插入入口：给已有表补 `SEED_WRITES`。
4. 表级更新入口：给已有表补 `SEED_UPDATES`。

公共字段 `deleted`、`tenancy`、`company_id`、`creator`、`create_time`、
`modifier`、`modify_time` 不建边。按精确列名排除，`affiliation_company_id` 可以建。

## 1. 写关系列表

一条边声明成「父列 → 子列」，脚本会自己做成库里的左右对：

```python
SeedEdge(
    parent="c12_mtp_db.uat_mtp.cs_dsly_highway_dispatch_order.dispatch_order_no",
    child="c12_mtp_db.uat_mtp.cs_dsly_highway_cargo.dispatch_order_no",
    code_cardinality="one_to_one",   # 只写父到子：one_to_one / one_to_many / unknown
    code_evidence="enforced",        # 见下表
    measured=SeedMeasurement("text", 183, 84, 84, 84, 84),
    reason="一句话，给以后读种子的人看，页面不展示",
)
```

`measured` 六个数字必须来自 UAT 实测，不要估。数据库结论由这些数字算出来，
不要手写 `db_cardinality`。

| 字段 | 含义 |
| --- | --- |
| `key_kind` | `numeric`（unset 当 0）或 `text`（unset 当 `''`）。`*_id` 一般是 numeric，`*_no` 一般是 text |
| `child_table_rows` | 子表 `deleted = 0` 的行数 |
| `child_rows_with_value` | 外键非空/非 unset 的行数 |
| `child_distinct_keys` | 这些值去重后的个数 |
| `parent_rows_with_value` / `parent_distinct_keys` | 父表同一口径 |
| `orphan_keys` | 子键在存活父行里找不到的个数 |

在攀枝花工作空间用 MCP `execute_database_query`，别名 `c12_mtp_db`，环境 `uat`。
子表基数（把表名列名换成目标）：

```sql
SELECT COUNT(*) AS table_rows,
       COUNT(NULLIF(dispatch_order_no, '')) AS rows_with_value,
       COUNT(DISTINCT NULLIF(dispatch_order_no, '')) AS distinct_keys
FROM uat_mtp.cs_dsly_highway_cargo
WHERE deleted = 0;
```

数值列把 `''` 换成 `0`。孤儿键用详情页「复算 SQL」同款 `LEFT JOIN ... parent.deleted = 0`。

代码结论枚举：

| `code_evidence` | 何时用 |
| --- | --- |
| `enforced` | 违反会抛（严格 `toMap`、写前查重跳过） |
| `single_write` | 只有单对象写入，没有挡住第二次 |
| `batch_allowed` | 批量或循环里父键可重复 |
| `no_write_path` | 找不到赋值 |
| `conflicted` | 证据对不上，留给人看 |

`many_to_one` 不要写入库：从子表侧打开时由读取层翻转。

两端表都必须出现在 `SEED_TABLES`。只被死列连上的表也会进清单，左栏默认隐藏。

## 2. 写关系详情点位

在已有 `SeedEdge.sites` 里追加 `SeedSite`。不记行号。`file` 相对攀枝花工作空间根，
形如 `backend/c12-mtp/.../FooService.java`。

| `kind` | 角色 | 倾向 | 典型样子 |
| --- | --- | --- | --- |
| `fresh_key_per_row` | 写 | 1:1 | 循环里取新单号，一号一行 |
| `caller_key_reuse` | 写 | 1:N | 父键来自入参，同批可重复 |
| `shared_key_fanout` | 写 | 1:N | 父键在循环外定好，多行共用 |
| `single_write` | 写 | 1:1 | `saveOrUpdate` 一次一行 |
| `unique_guard` | 写 | 1:1 | 父键已存在就 skip/抛 |
| `strict_to_map` | 读 | 1:1 | `toMap` 无 merge，重复即抛 |
| `lossy_read` | 读 | 1:N | `findFirst` 丢掉多余行 |
| `grouping_by` | 读 | 1:N | `groupingBy` 成 List |

有 `sites` 时，`code_cardinality` 必须被其中至少一处支持。`batchInsert` 本身不决定
1:N：循环里每轮新取号再挂一行，是 `fresh_key_per_row`，不是 `caller_key_reuse`。
这段读错曾经让四条边的代码结论反了。

详情里的体检 SQL 不用写进种子，查询层按端点生成。

## 3. 写表级插入入口

`SEED_WRITES` 认的是**被插入的表**，不是外键列：

```python
SeedWrite(
    table="c12_mtp_db.uat_mtp.cs_dsly_highway_cargo",
    kind="batch_insert",  # batch_insert / save_or_update / insert
    file=_CARRIER_ADMIN,
    method="batchCreateCarrierOrder",
    snippet="... cargoDao.batchInsert(insertCargoList);",
)
```

规则：

- 一张表 + 一个文件 + 一个方法只能有一条。同方法写货物和结算，记两条、各挂各表。
- 片段里要能看出是在写当前这张表的 DAO/Mapper，不要把一次方法里所有 `save` 揉进一张卡片。
- `table` 必须已在 `SEED_TABLES`。
- 空列表表示还没录入，不是「确认没有插入」。
- `update` / `batch_update` 不要写进这里，那是更新入口。

在 `c12-mtp` 里搜 `xxxDao.batchInsert`、`saveOrUpdate`、`insert(` 认领目标表对应的实体。

## 4. 写表级更新入口

`SEED_UPDATES` 认的是**被更新的表**，和插入入口同一套规则、另一份列表：

```python
SeedUpdate(
    table="c12_mtp_db.uat_mtp.cs_dsly_highway_cargo",
    kind="batch_update",  # batch_update / save_or_update / update
    file=_CARRIER_PORTAL,
    method="batchDispatchOrder",
    snippet="... cargoDao.batchUpdate(updateCargoList);",
)
```

规则：

- 一张表 + 一个文件 + 一个方法在更新列表里只能有一条。
- 同一方法先 `saveOrUpdate` 再 `update`（例如 `createAndPublish`），插入列表和更新列表各记一条。
- `table` 必须已在 `SEED_TABLES`。
- 空列表表示还没录入，不是「确认没有更新」。

在 `c12-mtp` 里搜 `xxxDao.update`、`batchUpdate`、`saveOrUpdate` 认领目标表对应的实体。

## 落地

改完种子后不要重启才能看到数据，跑脚本写库即可：

```bash
docker compose exec backend uv run --extra dev pytest tests/test_table_relation_query.py tests/test_table_relations_api.py -q
docker compose exec backend uv run python -m context_router.scripts.seed_table_relations \
  --workspace b9ce65eddc27437d9615177fbd07cb0a
```

攀枝花工作空间 ID 以库里为准；只有一个工作空间时可省略 `--workspace`。
源码在攀枝花仓库的 `backend/c12-mtp/`，路径按那个工作空间根写相对路径。
测数列连 UAT 的 `c12_mtp_db`（`uat_mtp`），不要用 TEST 的 `test_mtp`。

种子校验失败会直接拒绝整版写入。常见原因：公共字段建了边、计数自相矛盾、
代码结论没有点位支撑、插入入口用了关系点位或更新入口的 `kind`、更新入口用了插入
`kind`、同一表同一方法在同一份列表里写了两次。
