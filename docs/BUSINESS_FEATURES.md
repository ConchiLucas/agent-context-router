# 业务功能说明

本文件只说明项目的业务目标、核心能力和功能模块。调用链路和排查路径见 `docs/FRONTEND_BACKEND_FLOW.md`。

## 项目定位

Agent Context Router 是给 AI 编程助手使用的上下文路由工具。

它的核心价值是：让 AI 在处理编码任务前，先通过统一入口获取和任务最相关的项目上下文，并记录这次上下文选择、全文阅读和反馈过程。

## 核心目标

- 管理多个项目的上下文入口。
- 管理项目相关的 Markdown 文档、runbook、架构说明、排障记录等。
- 根据任务文本返回最相关的上下文文档。
- 记录每次上下文准备、文档阅读和反馈。
- 提供前端面板查看项目、文档、trace 和反馈情况。
- 提供 CLI 和 MCP 工具，方便 AI 编程助手调用。

## 当前不做的事情

当前项目不使用：

```text
向量
embedding
pgvector
document_chunks
```

当前项目不把代码仓库里 AI 可以自己检索的易变材料批量保存为受管文档：

```text
配置文件
package/go/pom/pyproject 等 manifest
数据库建表 SQL
代码目录里的细粒度源文件
```

这些内容需要时让 AI 直接读取项目目录。受管文档只保存稳定、精炼、长期有效的说明和入口索引。

当前检索方式是确定性的本地检索：

```text
关键词 + title + doc_type + area + tags + content_markdown
```

## 功能模块

### 1. 项目管理

用于登记一个需要被 AI 使用上下文的项目。

主要信息：

- 项目 slug
- 项目名称
- 项目根路径
- 项目描述
- 父项目
- 子项目数量
- 文档数量
- active 文档数量

主要用途：

- 作为上下文文档的归属。
- 作为 `ctx prepare --project <slug>` 的入口。
- 让一个大项目管理多个子项目，项目列表默认展示顶层项目，详情页再查看子项目。
- 生成项目级 `AI_CONTEXT_INDEX.md` 模板。

### 2. 文档管理

用于保存项目相关的稳定上下文说明文档。

优先保存：

- `AGENTS.md`
- `AI_CONTEXT_INDEX.md`
- 稳定的项目说明
- 稳定的业务边界说明
- 长期有效的开发约定

不建议保存：

- 配置文件原文
- 表结构 SQL 原文
- manifest 文件原文
- AI 可以按需从源码目录直接读取的细节文件

主要信息：

- 文档 ID
- 标题
- 来源路径
- 文档类型
- 所属 area
- tags
- status
- Markdown 正文

文档状态：

```text
active
stale
archived
```

只有 active 文档会参与当前上下文检索。

### 3. 上下文准备

这是项目的核心功能。

输入：

- project
- task
- area
- cwd
- entrypoint_path
- entrypoint_rule
- route_hint
- source
- agent_name
- max_documents

输出：

- trace_id
- area
- 入口来源信息
- 推荐文档列表
- 每个文档的 rank
- score
- reason
- excerpt
- follow-up read 命令

典型命令：

```bash
ctx prepare --project <project> --task "<task>"
```

如果入口索引已经判断出任务 area，可以直接传入：

```bash
ctx prepare --project <project> --area <area> \
  --entrypoint-path AI_CONTEXT_INDEX.md \
  --entrypoint-rule "<matched rule>" \
  --task "<task>"
```

AI 编程助手应先调用 prepare，再决定是否读取全文。

### 4. 文档全文读取

当 prepare 返回的 excerpt 不够时，AI 可以读取全文。

典型命令：

```bash
ctx read <doc-id> --trace <trace-id> --reason "<why needed>"
```

读取全文时默认必须带上 trace 和 reason，系统会记录 read 事件。管理或调试场景可以显式使用 `untracked=true` 读取，但这类读取不会进入 trace。

### 5. Trace 记录

Trace 用于记录一次上下文准备过程。

Trace 包含：

- 任务文本
- 项目
- area
- cwd
- 入口索引路径
- 命中的入口规则
- route hint
- 调用来源
- 返回过哪些文档
- 每个文档的 score/reason/rank
- 后续读取过哪些全文
- 用户或开发者对推荐结果的反馈

Trace 的意义：

- 复盘 AI 为什么读了某些文档。
- 判断上下文推荐是否准确。
- 发现过期、不必要或缺失的文档。

### 6. 推荐反馈

前端 Trace 详情页可以标记推荐文档的反馈。

当前反馈类型：

```text
useful
unnecessary
stale
missing
```

反馈用于后续改进文档质量和路由规则。

### 7. 前端面板

前端主要是审计和查看用途，不是主要数据录入入口。

当前页面：

- Dashboard：查看项目、文档、trace、反馈指标。
- Projects：查看顶层项目列表。
- Project Detail：查看项目详情、子项目和 AI_CONTEXT_INDEX 模板。
- Documents：查看和筛选上下文文档。
- Traces：查看 prepare 调用历史。
- Trace Detail：查看返回文档、read 事件和反馈。

### 8. CLI 能力

CLI 是当前主要操作入口之一。

常用命令：

```bash
ctx project add
ctx project init-index
ctx doc add
ctx prepare
ctx read
ctx trace
```

### 9. MCP 能力

MCP server 用于让 AI 编程助手直接调用上下文路由能力。

当前工具：

```text
prepare_task_context
read_context_document
```

## 业务边界

这个项目负责：

- 管理上下文文档。
- 推荐任务相关文档。
- 记录 AI 上下文使用行为。
- 提供排查和反馈闭环。

这个项目不负责：

- 替代代码仓库本身。
- 存储所有项目知识。
- 自动判断最终代码修改方案。
- 做复杂权限系统。
  - 做向量语义检索。
