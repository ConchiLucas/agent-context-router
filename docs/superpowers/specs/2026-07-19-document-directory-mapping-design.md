# Context Router 文档目录映射设计

日期：2026-07-19  
状态：已完成讨论，等待书面设计确认

## 1. 背景与目标

Context Router 当前使用 Project `root_path` 同时识别代码项目和读取项目仓库内的文档。新的文档管理方式会把所有项目文档集中维护在服务器上的统一目录中，代码目录和文档目录不再位于同一个位置。

本次改造只解决文档映射和分层阅读：

1. 继续根据 AI 传入的 `cwd` 识别当前代码项目。
2. 将每个代码项目唯一映射到统一文档根目录下的一个文档项目。
3. 只索引该文档项目根部的 `AGENTS.md` 和 `docs/**/*.md`。
4. 让 AI 从 `AGENTS.md` 开始，沿 Markdown 链接按需逐层阅读。
5. 在 Tasks 中只记录 AI 实际调用 MCP 后走过的阅读链路。
6. 让开发者通过 Projects 页面选择映射、手动同步并查看文档健康状态，不要求执行命令。

本功能不判断任务是否完成，不收集人工反馈，也不要求 AI 解释为什么没有调用 MCP 或为什么停止阅读。

本文档是现有 MCP-only 设计的增量设计；涉及“文档仍在代码项目目录”和“prepare 返回最多三份检索候选”的旧规则，以本文档为准。其他 MCP 无状态调用和 Tasks 客观链路规则继续保留。

## 2. 已确认的核心决策

- 统一文档目录是唯一文档真源，代码项目目录中的同名文档不再作为回退来源。
- 一个代码项目最多映射一个文档项目；一个文档项目也只能映射给一个代码项目。
- 使用 Docker 只读 bind mount 将宿主机统一文档目录挂载到 Context Router 后端。
- 不复制文档，不在 Context Router 仓库创建软链接，也不把正文迁入数据库维护。
- `root_path` 继续表示代码项目路径，只用于 `cwd` 匹配。
- 新增 `docs_path` 表示统一文档根目录下的相对路径，只用于定位文档。
- 第一版由开发者在网页点击 `Sync Documents` 手动同步，不增加文件 watcher 或后台轮询。
- MCP 的入口固定为 `AGENTS.md`，后续文档只能沿已索引的 Markdown 链接读取。
- 文件夹层级用于组织文件；AI 的有效阅读层级由从 `AGENTS.md` 出发的链接关系决定。

## 3. 目录约定与部署

宿主机统一目录示例：

```text
/srv/ai-docs/
├── order-docs/
│   ├── AGENTS.md
│   └── docs/
│       ├── business.md
│       └── database/
│           └── schema.md
└── user-docs/
    ├── AGENTS.md
    └── docs/
        └── authentication.md
```

每个文档项目必须满足：

```text
<document-project>/
├── AGENTS.md       # 根目录唯一允许索引的 Markdown 文件
└── docs/
    └── **/*.md     # 递归索引
```

文档项目根目录中的其他 Markdown 文件不索引；`docs/` 之外的目录也不扫描。扫描器忽略软链接文件和软链接目录。

部署配置：

```text
CONTEXT_ROUTER_DOCUMENTS_HOST_ROOT=/srv/ai-docs
CONTEXT_ROUTER_DOCUMENTS_CONTAINER_ROOT=/documents
```

Docker Compose 将宿主机路径以只读方式挂载：

```yaml
volumes:
  - /srv/ai-docs:/documents:ro
```

后端只使用 container root 读取文件；host root 用于配置展示和必要的路径换算。HTTP API 不接收任意绝对文档路径。

## 4. 项目映射模型

### 4.1 Project 字段

保留：

- `root_path`：代码项目的宿主机路径，供 `prepare_task_context` 按 `cwd` 最长前缀匹配。

新增：

- `docs_path`：相对统一文档根目录的文档项目路径，可空，建立映射后唯一。
- `last_synced_at`：最近一次成功同步时间，可空。
- `last_sync_status`：`never`、`success` 或 `failed`。
- `last_sync_summary`：最近一次同步的客观统计，保存 indexed、reachable、orphan、broken link 和 pruned 数量。

第一版继续保留字段名 `root_path`，不做无收益的数据库重命名。`docs_path` 在数据库建立唯一约束；空值允许多个项目存在。

首次保存或更换 `docs_path` 时，Project 的同步状态重置为 `never`，最近同步统计清空。MCP 必须等新映射完成一次成功同步后才能使用，不能把旧映射的索引当作新映射内容。

### 4.2 路径解析

示例：

```text
MCP cwd                       /srv/projects/order-service
Project.root_path             /srv/projects/order-service
Project.docs_path             order-docs
Container documents root      /documents
Resolved document root        /documents/order-docs
```

映射保存和每次使用时都必须验证：

- `docs_path` 是相对路径，不能是绝对路径，不能包含 `..`。
- 解析后的真实路径位于配置的 documents root 内。
- 映射目标本身不是软链接，真实路径不能通过软链接逃逸根目录。
- 目标是目录，并同时包含普通文件 `AGENTS.md` 和普通目录 `docs/`。
- 目标未被其他 Project 使用。

Projects 页面只展示服务端发现的合法候选目录，开发者不手写绝对路径。候选发现只检查 documents root 的直接子目录；未来确有多层文档项目分组时再扩展。

## 5. 文档格式与链接图

### 5.1 稳定标识

`AGENTS.md` 和每一份 `docs/**/*.md` 都必须具有 YAML front matter，并包含稳定、非空的 `doc_id`：

```markdown
---
doc_id: order-project-entry
title: 订单服务文档入口
doc_type: agent_index
---

# 订单服务文档入口
```

规则：

- `doc_id` 是 MCP 和历史 Trace 使用的稳定标识，文件改名时不得随意改变。
- 沿用现有数据库约束，`doc_id` 在所有项目之间全局唯一。
- 同一同步批次或数据库中出现重复 `doc_id` 时，同步整体失败，不做部分写入。
- `AGENTS.md` 的 `doc_type` 固定归一为 `agent_index`；其他文档未声明时使用现有默认类型。
- 缺少 `doc_id` 的文件是同步错误，不再静默跳过，避免页面看似成功但 MCP 无法阅读。

### 5.2 有效层级

有效层级来自 Markdown 链接图：

```text
AGENTS.md
  -> docs/business.md
      -> docs/database/schema.md
```

- `AGENTS.md` 是唯一第一层入口。
- `AGENTS.md` 的直接链接目标是第二层。
- 第二层文档的直接链接目标是第三层，以此类推。
- 文件系统目录深度不直接授予阅读权限，也不替代 Markdown 链接。
- 同一文档可被多个父文档链接；用于索引展示的层级取从 `AGENTS.md` 出发的最短路径。
- 链接图允许汇合和环；遍历计算使用已访问集合，不能无限递归。
- 文件存在但无法从 `AGENTS.md` 到达时标记为 orphan，不提供给 MCP 阅读，但仍在 Web 中展示供维护。

### 5.3 链接解析

第一版解析普通内联 Markdown 文档链接：

```markdown
[数据库说明](./database/schema.md)
```

解析规则：

- 相对路径以当前 Markdown 文件所在目录为基准。
- URL decode 后去掉 `#fragment`，目标必须是 `.md` 文件。
- HTTP(S)、`mailto:`、纯锚点和图片链接忽略，不进入文档图。
- 目标必须是当前映射目录中的 `AGENTS.md` 或 `docs/**/*.md` 普通文件。
- 指向允许范围内但不存在、缺少 `doc_id` 或未能索引的目标，记录为 broken link。
- 引用式 Markdown 链接和非 Markdown 文件链接不在第一版范围内。

## 6. 手动同步流程

开发者完成映射后，在 Projects 页面点击 `Sync Documents`：

1. 后端重新验证映射目录和边界。
2. 读取根 `AGENTS.md`。
3. 递归扫描 `docs/**/*.md`，忽略其他位置和所有软链接。
4. 解析 front matter、标题、元数据和 Markdown 链接。
5. 在内存中验证必需字段、全局 `doc_id` 唯一性和所有路径。
6. 从 `AGENTS.md` 计算 reachable、orphan、broken link 和最短展示深度。
7. 在单个数据库事务中更新文档索引和链接。
8. 将该 Project 中本次已不存在的文档移出当前可用索引并删除相关链接；已有任务历史保留。
9. 更新最近同步状态和统计。

同步必须是原子的。解析或验证失败时回滚文档和链接变更，将 `last_sync_status` 记为 `failed`，并返回可在网页直接理解的错误；不能留下半套新索引。

同一映射此前已有成功索引时，一次失败的重新同步不破坏旧的完整索引，MCP 可继续使用该旧索引；页面同时展示“最近一次同步失败”和最近成功时间。映射刚建立或刚更换而尚未成功同步时没有可用旧索引，MCP 必须报错。

数据库保存用于列表、关系和历史关联的索引。MCP 全文读取时始终从映射后的只读文件系统读取最新正文，不使用旧的 `content_markdown` 兜底。因此：

- 只修改正文且不修改 front matter 或链接时，下一次读取立即看到新正文。
- 新建、删除、改名、修改 `doc_id`、元数据或链接后，需要再次点击同步。
- 文件在同步后被删除时，MCP 读取明确失败并提示重新同步，不返回数据库旧正文。

“pruned”表示文档不再属于当前可用索引。没有历史引用的记录可以删除；被 RetrievalHit 或历史事件引用的文档保留为不可读取的 tombstone 元数据，以便旧 Task 继续显示当时的候选标题和标识。tombstone 不计入当前文档统计，也不能被 prepare 或 read 使用。

## 7. MCP 数据流与访问约束

### 7.1 `prepare_task_context`

```text
task + cwd
  -> 按 root_path 识别代码 Project
  -> 读取 Project.docs_path 映射
  -> 校验最近索引中的 AGENTS.md
  -> 创建 MCP Trace
  -> 只返回 AGENTS.md 这一份入口候选
```

`prepare_task_context` 不再对全部文档做最多三份候选检索，不直接返回第二层或更深文档。其返回仍包含 `trace_id` 和文档标识，AI 自主决定是否继续调用 read。

没有映射、映射不可用或入口未成功同步时，prepare 返回可操作错误且不创建无意义 Trace。AI 可以自行检索代码，系统不要求它记录原因。

### 7.2 `read_context_document`

读取规则：

- 一个 Trace 的第一次 read 只能读取 prepare 返回的 `AGENTS.md`，且不传 `parent_document_id`。
- 后续 read 必须传 `parent_document_id`。
- parent 必须已在同一 Trace 中成功读取。
- requested document 必须是 parent 在最近同步索引中的直接有效链接目标。
- requested document 必须属于该 Trace 的映射 Project，且处于 reachable 集合中。
- depth 由后端根据该 Trace 中 parent 的实际 read depth 加一，AI 不传 depth。
- Web 预览使用 untracked 读取，不受 MCP 链路约束，也不生成 AI read event。

成功后，后端实时读取文件正文，返回该文档及其有效的下一层链接，并记录 read event。broken link 不返回给 AI，只在 Web 维护视图中展示。

这使 Tasks 中看到的父子关系等于 AI 真实走过的路径，而不是同步阶段推测出的最短路径。

## 8. Web 交互设计

### 8.1 Projects 列表

每张 Project 卡片展示：

```text
Code root           /srv/projects/order-service
Document mapping    order-docs
Status              Ready / Not mapped / Invalid / Sync failed
AGENTS.md            Ready / Missing
Documents            18 indexed · 15 reachable · 3 orphan
Broken links         2
Last synced          2026-07-19 16:30
```

操作：

- `Map Documents` / `Change Mapping`
- `Sync Documents`
- `Documents`
- `Tasks`

未映射或映射无效时禁用同步，并展示原因。

### 8.2 映射选择器

点击映射按钮打开选择器：

- 列出 documents root 下符合目录约定的候选目录。
- 展示目录名、是否已映射、AGENTS 状态和 Markdown 文件数量。
- 已被其他 Project 使用的目录可见但不可选择，并标出所属项目。
- 保存前由服务端再次验证，不能依赖前端检查。
- 第一次保存映射不自动同步，避免隐式执行耗时操作；保存后页面明确提示点击 Sync Documents。

### 8.3 同步结果

同步完成后展示：

- indexed：本次成功索引的文档总数。
- reachable：可从 `AGENTS.md` 到达的文档数，包含 `AGENTS.md`。
- orphan：存在但不可从入口到达的文档数。
- broken links：无法解析到有效索引文档的本地 Markdown 链接数。
- pruned：本次删除的旧索引数。

Documents 页面继续提供文档列表、预览和关系图，同时明确区分 reachable、orphan 和 broken link，帮助开发者优化文档树。

### 8.4 Tasks 链路

Tasks 外层仍是任务列表，详情按实际 MCP 调用显示：

```text
prepare_task_context
  -> returned AGENTS.md
read_context_document AGENTS.md
  -> read_context_document business.md
      -> read_context_document schema.md
```

页面不添加评分、反馈、不读原因或停止阅读原因。

## 9. API 边界

后端增加或调整以下内部 HTTP 能力：

- 获取合法文档目录候选及占用状态。
- 为 Project 保存或更换 `docs_path` 映射。
- `Sync Documents` 不再接收任意 `docs_dir`，只同步 Project 当前映射。
- Project list/detail 返回映射、同步状态和统计。
- Document list 返回 reachable、orphan、最短展示深度和 broken link 信息。
- MCP prepare/read 使用映射解析器和链接访问校验器。

具体 URL 命名沿用现有 FastAPI router 风格，在实施计划中按测试先行拆分。所有 HTTP API 仍是 MCP server 和 Web 的内部实现，不新增开发者命令行入口。

建议把职责拆为独立单元：

- `DocumentRootResolver`：配置根目录、映射路径解析和 containment 校验。
- `DocumentMappingService`：候选发现、唯一占用检查和保存映射。
- `MappedDocumentSync`：固定范围扫描、解析、原子写入和健康统计。
- `DocumentGraphPolicy`：reachable、orphan、最短深度和 direct-link 校验。
- `MappedDocumentReader`：按索引路径实时、安全地读取正文。

这些单元不依赖前端，并可分别进行单元测试。

## 10. 错误处理

| 情况 | Web 行为 | MCP 行为 |
| --- | --- | --- |
| Project 未映射 | 显示 Not mapped，禁用 Sync | prepare 返回映射缺失错误，不创建 Trace |
| 映射目录不存在 | 显示 Invalid | prepare 返回映射不可用，不回退代码目录 |
| `AGENTS.md` 缺失或无 `doc_id` | 显示 Invalid / Sync failed | prepare 不返回入口 |
| `docs/` 缺失 | 显示 Invalid | prepare 返回映射不可用 |
| 重复 `doc_id` | 同步失败并指出冲突文件 | 继续使用上次完整成功索引；若入口不可读则报错 |
| broken link | 显示来源、标签和目标 | 不把该链接返回给 AI |
| orphan 文档 | 在 Documents 中标记 | 不允许 MCP 沿链路读取 |
| 同步后文件删除 | 提示重新同步 | read 404，不返回缓存正文，不记录成功 read |
| `docs_path` 路径逃逸 | 拒绝保存并记录服务端错误 | 不访问 documents root 外文件 |
| 文档被其他项目占用 | 选择器禁用并显示项目 | 不允许建立第二个映射 |

历史 Trace 不因重新映射或同步而删除。历史事件继续显示当时记录的 document id、title、parent 和 depth；若历史文档已不存在，详情仍可展示事件，但正文预览可以不可用。

## 11. 数据迁移与兼容策略

- 使用 Alembic 为 Project 新增映射和同步状态字段，并为非空 `docs_path` 建唯一约束。
- 现有 Project 的 `docs_path` 初始为空；不根据 `root_path` 自动猜测，不自动复制或删除旧索引。
- 开发者在 Web 为每个项目建立映射并首次同步后，新链路才启用。
- 首次成功同步会清理该 Project 不属于映射目录的当前可用索引，但保留历史 Trace、Event 和候选快照所需的 tombstone 元数据。
- 现有 `documents.id` 全局主键、Trace 表和 MCP 工具名称保持不变。
- `content_markdown` 列暂时保留用于兼容列表/预览结构，但不得成为 MCP 文件缺失时的正文回退。
- 原有检索排序模块可以保留在代码中供历史兼容，但新的 MCP prepare 不再调用它；确认无其他消费者后再单独清理，不扩大本功能范围。

## 12. 测试设计

### 12.1 后端

- `cwd` 最长匹配到代码 Project，再解析到唯一 `docs_path`。
- 未映射、无效映射、绝对路径、`..`、软链接和 realpath 逃逸均被拒绝。
- 同一 `docs_path` 不能绑定多个 Project。
- 候选发现只返回 documents root 的合法直接子目录。
- 扫描范围严格为根 `AGENTS.md` 加 `docs/**/*.md`，忽略其他 Markdown 和软链接。
- 所有索引文档必须有全局唯一 `doc_id`；错误时事务回滚。
- Markdown 链接正确解析相对路径、fragment 和 URL encoding。
- 正确计算 reachable、orphan、broken link、环和最短展示深度。
- 同步成功会 prune 已删除索引并保留历史 Trace/Event。
- 被历史候选引用的已删除文档转为 tombstone，旧 Task 仍能显示候选而 MCP 不能再读取。
- prepare 只返回 AGENTS，不调用旧的候选排序。
- 第一次 read 只能读取 AGENTS；后续 read 只能沿已读 parent 的直接有效链接。
- 多父节点时索引展示取最短深度，Task 事件记录实际 parent/depth。
- 文件同步后删除时实时读取失败，不能返回缓存正文或记录成功 read。
- Web untracked preview 不生成 Trace read event。

### 12.2 前端

- Project 卡片正确显示 code root、mapping、状态和同步统计。
- 映射选择器正确显示可用、占用和无效候选。
- 未映射或无效时 Sync 按钮禁用并显示原因。
- 保存映射后提示手动同步，不隐式触发同步。
- 同步结果显示 indexed、reachable、orphan、broken link 和 pruned。
- Documents 关系视图区分 reachable、orphan 和 broken link。
- Task 详情仍只显示 prepare 和真实 read 链路，不出现反馈或原因字段。

### 12.3 部署与回归

- Docker Compose 后端能以只读方式访问 container documents root。
- 后端无法写入统一文档目录。
- 现有 MCP stdio server、Tasks 历史列表和 Web untracked 预览保持可用。
- 后端 pytest、ruff、migration upgrade 与前端 test、lint、isolated build 全部通过。

## 13. 验收标准

功能完成后，开发者无需使用命令即可：

1. 在 Projects 页面把代码项目映射到一个统一文档目录。
2. 点击一次同步，看到文档总数、可达文档、孤立文档和断链。
3. 更新统一目录里的正文后，让 MCP 下一次 read 立即读取新正文。
4. 新增或调整文档链接后，通过再次同步更新图。
5. 在 Tasks 列表进入详情，看到 AI 从 AGENTS 开始实际阅读了哪些文档以及父子顺序。

同时，AI 不能通过 Context Router MCP 绕过 AGENTS 直接读取深层文档，也不能读取映射目录之外的文件。

## 14. 第一版非目标

- 自动监听文档变化或定时同步。
- 同时配置多个统一文档根目录。
- 一个代码项目映射多个文档项目。
- 在 Web 中编辑或上传 Markdown。
- 复制、生成或软链接外部文档。
- prepare 直接搜索并返回深层候选文档。
- 记录 AI 未调用、不读或停止阅读的原因。
- 任务完成度、成功率、质量评分和人工反馈。
- 删除历史 Trace、旧数据库字段或一次性重构所有检索代码。
