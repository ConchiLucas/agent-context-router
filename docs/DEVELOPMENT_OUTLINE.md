# 开发功能清单

本文件只做简要功能清单，用来快速判断项目里有哪些功能、各自是做什么的。具体实现细节按需查看对应文档。

## 功能清单

### 项目管理

用于登记需要被 AI 使用上下文的项目，维护项目 slug、名称、根路径、描述、文档数量和父子项目层级。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 文档管理

用于保存项目相关的稳定说明和入口索引，例如 `AGENTS.md`、`AI_CONTEXT_INDEX.md`。配置、表结构、manifest 和源码细节让 AI 按需直接读取项目目录。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [数据库信息](./DATABASE_INFO.md)

### 文档树读取

用于让 AI 从 `AGENTS.md` / `AI_CONTEXT_INDEX.md` 开始，按下一层 doc-id 使用 `ctx read <doc-id>` 逐层读取上下文，是当前项目的核心使用方式。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 兜底上下文检索

用于在 AI 不知道该读哪个 doc-id 时，根据 project、area 和关键词返回候选文档。当前使用关键词、标题、类型、area、tags 和完整文档正文做确定性检索。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 文档全文读取

用于按 doc-id 读取完整文档，系统自动把读取事件挂到当前调用链路。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### Trace 记录

用于记录 AI 读取了哪些文档、兜底检索返回过哪些文档、推荐分数、原因和反馈。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 推荐反馈

用于标记推荐文档是否 useful、unnecessary、stale 或 missing，帮助后续判断上下文质量。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 前端面板

用于查看项目、文档、trace、反馈和整体指标；文档页默认展示“总入口 -> 使用协议 / 任务路由 / 子项目入口 -> 子路由文档”的关系图，图中每个卡片都是可打开的受管文档，并展示下一步命令提示。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### Usage 卡片

用于在前端维护可复用的 AI 使用说明卡片，例如 ctx/SESSION_ID 使用方式；卡片以 Markdown 保存，支持新增、预览和编辑。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### CLI

用于通过命令行创建项目、添加文档、准备上下文、读取全文和查看 trace。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### MCP

用于让 AI 编程助手直接调用上下文准备和文档读取能力。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 本地启动与验证

用于规范本地启动、重启、测试、lint、build 和 migration。统一使用 Docker Compose。

细节参考：

- [启动与开发规范](./STARTUP_GUIDE.md)

### 数据库

用于记录当前项目数据库连接、表结构状态、migration 版本和常用检查命令。

细节参考：

- [数据库信息](./DATABASE_INFO.md)

### 项目改进建议

用于规划后续能力和拆分开发优先级，只在评估新功能或路线时读取。

细节参考：

- [项目改进建议](./IMPROVEMENT_PLAN.md)

## 开发记录

代码层面的功能开发、bug 排查、架构决策和重要变更记录在：

- [开发细节目录](./development-details/README.md)
