# 按表名补全表关联

你读完本文就可以开工。用户只需要给你**一张表名**（例如 `cs_dsly_highway_cargo`）。
你的任务不是写报告就停，而是：**检查四层数据是否完整，缺什么就补什么，跑种子落地，最后用一张清单告诉用户结果。**

不要先去读设计长文。字段写法需要对照时再打开
[表关联种子怎么写](./table_relation_seed.md)。
改动只发生在种子文件，不要直接写 PostgreSQL 投影表。

唯一改动文件：

`backend/src/context_router/scripts/seed_table_relations.py`

仓库：`agent-context-router`。Java 源码和 UAT 库在攀枝花工作空间，不在本仓库。

---

## 0. 接到表名后立刻做的事

1. 把用户给的名字收成短表名，如 `cs_dsly_highway_cargo`。允许带 schema 前缀，丢掉即可。
2. 一次只做这一张表。用户一次给多张就按顺序各做一遍，不要并行改同一个种子文件。
3. 已有条目只要本身是对的就不要改。只在 tuple **末尾追加**，或给**空的 `sites`** 补点位。
4. 四层互不推导：关系边、边上的详情点位、表级插入、表级更新是四份东西。货物一次 `batchInsert` 填了四个外键，按边聚合会重复，父表上还会显示成「写入了父表」。
5. 做完必须跑种子。只改文件不跑脚本，页面不会变。

固定坐标：

| 项 | 值 |
| --- | --- |
| 种子前缀 `MTP` | `c12_mtp_db.uat_mtp` |
| 库别名 | `c12_mtp_db` |
| Schema | `uat_mtp` |
| 环境 | `uat`（不要用 `test_mtp`） |
| 攀枝花工作空间 ID | `b9ce65eddc27437d9615177fbd07cb0a` |
| Java 根 | `/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce` |
| 源码相对路径 | `backend/c12-mtp/...`（相对攀枝花根，禁止绝对路径，禁止行号） |
| 公共字段，永不建边 | `deleted` `tenancy` `company_id` `creator` `create_time` `modifier` `modify_time` |

测数列：对攀枝花工作空间调用 Context Router MCP。
`cwd` 用 `/Users/conchi/workforce/company_workforce/panzhihua_dev_workforce`，
`environment=uat`，然后 `read_task_context` 确认别名是 `c12_mtp_db`，再用
`execute_database_query`。从本仓库 `cwd` prepare 经常匹配不到工作空间，换攀枝花根再 prepare，不要卡住。

---

## 1. 完整的定义（缺一条就补）

针对**用户点名的那张表 T**，四层都要过关。

### 1.1 关系列表完整

- `SEED_TABLES` 里有 `c12_mtp_db.uat_mtp.{T}`。
- 每一条「T 持有外键，指向别人」的边都在 `SEED_EDGES`。
- 每一条「别人持有外键，指向 T」的边都在 `SEED_EDGES`。
- 每条边都有 UAT 实测六个数字，**禁止估算**。
- 对端表不在 `SEED_TABLES` 时先登记对端表，但**不要顺便把对端表的插入/更新入口也做完**，除非用户点了那张表。

候选列从两处交叉得到，只保留两边都说得通的：

1. Java 实体字段（见第 2 步）里，代码会赋成**另一张表的主键或业务单号**的列。
2. UAT 里该列有值，并能 JOIN 到对端存活行（或明确是死列：表有行、这列全空）。

不要建边的：公共字段、纯描述拷贝（已有 `category_id` 时的 `category_name`）、数量/金额/状态/时间、本表自己的主键。
`affiliation_company_id` 可以建，因为它不是公共名单里的 `company_id`。

找不到任何外键赋值，也找不到别人指向 T 的列：关系列表以空为完整，左栏这张表会被「只看有关联的表」藏起来。在最终报告里写明「已搜过，没有可建的边」。

### 1.2 关系详情完整

看**以 T 为一端**的每一条 `SEED_EDGES`：

| 代码依据 | 详情怎样算完整 |
| --- | --- |
| `enforced` / `single_write` / `batch_allowed` | `sites` 非空，且至少一处的倾向等于 `code_cardinality`；`enforced` 必须有 `unique_guard` 或 `strict_to_map`；`single_write` 必须有 `fresh_key_per_row` 或 `single_write`；`batch_allowed` 必须有 `caller_key_reuse` 或 `shared_key_fanout` |
| `no_write_path` | `sites` 必须没有写入类点位；空 tuple 即可 |
| `conflicted` | 可以有对不上的点位，留给人看 |

`batchInsert` **不是** 1:N。循环里每轮新取号再挂一行，是 `fresh_key_per_row`（1:1）。这段读错曾经让四条边反了。

体检 SQL 不用写进种子。

### 1.3 插入入口完整

在 `c12-mtp` 里穷尽搜索 T 对应实体的插入调用（见第 4 步）。
每一个不同的 `(相对路径, 方法名)` 都必须有一条 `SEED_WRITES`。
同方法写两张表，各挂各表，各记一条。

搜完为零：插入列表保持空，这算完整，报告里写「已搜过，没有插入调用」。
没搜就留空：不完整，必须搜。

### 1.4 更新入口完整

同样穷尽搜索更新调用，写入 `SEED_UPDATES`。
同一方法先插入再更新（`saveOrUpdate` 随后 `update`），**两份列表各记一条**。

`kind` 不要混用：插入只用 `batch_insert` / `save_or_update` / `insert`；
更新只用 `batch_update` / `save_or_update` / `update`。

---

## 2. 定位 Java 实体和 DAO

在攀枝花源码根搜索：

```text
@Table(name = "cs_dsly_highway_cargo")
```

记下实体类（如 `HighwayCargo`）和模块路径。再找：

```text
class HighwayCargoDao
```

DAO 字段名通常是 `cargoDao`、`inboundOrderDao` 这种。后面搜索插入/更新时用 **DAO 变量名 + 调用**，不要只搜实体名。

列清单：读实体字段，去掉公共字段和明显的非键（数量、金额、状态、时间、名称拷贝）。
剩下的 `*Id` / `*No` 就是关系候选。对每个候选，在源码里搜 `setXxx` 看值从哪张表来。

别人指向 T：搜 T 的业务键在其他实体上的 setter，例如货物表搜 `setDispatchOrderNo`、`setCarrierOrderNo` 出现在哪些 `buildXxx` 里。

---

## 3. 补关系列表

对每个确认的「父列 → 子列」：

1. 两端表都写入 `SEED_TABLES`（已有则跳过）。
2. 判定键类型：`*_id` 一般 `numeric`（unset 当 `0`），`*_no` 一般 `text`（unset 当 `''`）。拿不准就读实体字段类型。
3. 用 UAT 跑下面三条 SQL，把数字填进 `SeedMeasurement`。`orphan_keys` 省略时默认 0，有孤儿必须写。
4. 读代码写 `code_cardinality`（只允许父到子的 `one_to_one` / `one_to_many` / `unknown`）和 `code_evidence`。**不要手写 `db_cardinality`**，脚本用计数推导。
5. `many_to_one` 不要入库，从子表打开时读取层会翻转。
6. 在 `SEED_EDGES` 末尾追加。已有同一对 parent/child 就不要再加一条，改为补它的 `sites` 或纠正测错的数字。

子表基数（列名按实际改；数值列把 `''` 换成 `0`）：

```sql
SELECT COUNT(*) AS table_rows,
       COUNT(NULLIF(dispatch_order_no, '')) AS rows_with_value,
       COUNT(DISTINCT NULLIF(dispatch_order_no, '')) AS distinct_keys
FROM uat_mtp.cs_dsly_highway_cargo
WHERE deleted = 0;
```

父表同一口径，去掉 `table_rows` 即可。孤儿键：

```sql
SELECT COUNT(DISTINCT child.dispatch_order_no) AS orphan_keys
FROM uat_mtp.cs_dsly_highway_cargo AS child
LEFT JOIN uat_mtp.cs_dsly_highway_dispatch_order AS parent
       ON parent.dispatch_order_no = child.dispatch_order_no
      AND parent.deleted = 0
WHERE child.deleted = 0
  AND NULLIF(child.dispatch_order_no, '') IS NOT NULL
  AND parent.dispatch_order_no IS NULL;
```

数据库结论（你不用写，但补边前要心里有数）：子表 0 行 → 无数据；有行但这列全空 → 死列（列表会隐藏）；去重键 < 有值行 → 1:N；否则行数 ≥ 20 才是测成的 1:1，少于 20 是样本不足的 1:1。

代码依据：`enforced` 违反会抛；`single_write` 只有单对象写；`batch_allowed` 批量或循环里父键可重复；`no_write_path` 找不到赋值；`conflicted` 对不上。

---

## 4. 补关系详情点位

对 1.2 判定不完整的边，打开赋值附近的 Java，记下：

- `file`：相对攀枝花根，如 `backend/c12-mtp/c12-mtp-highway-service/.../FooService.java`
- `method`：所在方法名
- `snippet`：能定位的几行，1～2000 字，必须能在文件里搜到
- `kind`：

| kind | 角色 | 倾向 | 典型样子 |
| --- | --- | --- | --- |
| `fresh_key_per_row` | 写 | 1:1 | 循环里取新单号，一号一行 |
| `caller_key_reuse` | 写 | 1:N | 父键来自入参，同批可重复 |
| `shared_key_fanout` | 写 | 1:N | 父键在循环外定好，多行共用 |
| `single_write` | 写 | 1:1 | `saveOrUpdate` 一次一行 |
| `unique_guard` | 写 | 1:1 | 父键已存在就 skip/抛 |
| `strict_to_map` | 读 | 1:1 | `toMap` 无 merge，重复即抛 |
| `lossy_read` | 读 | 1:N | `findFirst` 丢掉多余行 |
| `grouping_by` | 读 | 1:N | `groupingBy` 成 List |

有 `sites` 之后，若代码结论不再被点位支持，**改正代码结论**，不要删点位去迁就旧结论。

---

## 5. 补插入入口

在 `backend/c12-mtp` 搜索（把 `cargoDao` 换成这张表的 DAO 变量）：

```text
cargoDao.batchInsert
cargoDao.saveOrUpdate
cargoDao.insert(
```

每个命中读所在方法：确认插入的是 **T 的实体**，不是顺手保存的别的表。
`kind`：`batchInsert` → `batch_insert`；单行 `saveOrUpdate` 且这是新建路径 → `save_or_update`；单行 `insert` → `insert`。
`update` / `batchUpdate` 不要写进 `SEED_WRITES`。

一条 `SeedWrite`：`table=f"{MTP}.{T}"`，`file` 相对路径，`method`，能看出当前表 DAO 的片段。
已有 `(table, file, method)` 就跳过。

---

## 6. 补更新入口

同样搜索：

```text
cargoDao.batchUpdate
cargoDao.update(
cargoDao.saveOrUpdate
```

`saveOrUpdate` 出现在「改已有行」的路径时记入 `SEED_UPDATES`，即使插入列表里已经有同一方法。
`kind`：`batchUpdate` → `batch_update`；`update(` → `update`；更新语义的 `saveOrUpdate` → `save_or_update`。

---

## 7. 落地

改完种子后，在 **agent-context-router 仓库根**执行，不要在宿主机直接跑 pytest：

```bash
docker compose exec backend uv run --extra dev pytest tests/test_table_relation_query.py tests/test_table_relations_api.py -q
docker compose exec backend uv run python -m context_router.scripts.seed_table_relations \
  --workspace b9ce65eddc27437d9615177fbd07cb0a
```

只改种子、跑脚本就够，**不要**为了看数据去重启后端。
脚本按 `(workspace_id, environment)` 整版覆盖，所以可以反复跑。
校验失败会拒绝整版：公共字段建了边、计数自相矛盾、代码结论没有点位支撑、插入/更新用错 `kind`、同一表同一方法在同一份列表里写了两次。

---

## 8. 交还给用户的格式

四层都处理完再回复，不要中途只报缺口。用这张表：

```text
表：cs_dsly_highway_cargo
关系列表：已有 4 条，新增 1 条，完整
关系详情：4 条已有点位，1 条补了点位，完整
插入入口：已有 2 处，新增 0 处，完整
更新入口：已有 1 处，新增 2 处，完整
说明：……（死列、搜过但没有写入、测不到基数、MCP 失败等）
```

某一层实在补不成（表不存在、没有 Java 实体、UAT 查不了），在该层写「未完成」和原因，**不要假装完整**。其他层能补的仍然补完。
