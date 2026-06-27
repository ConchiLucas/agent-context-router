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

### 上下文准备

用于根据任务文本返回最相关的上下文文档，是项目的核心能力。当前使用关键词、标题、类型、area、tags 和完整文档正文做确定性检索。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 文档全文读取

用于在上下文摘要不够时读取完整文档，并记录读取原因。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### Trace 记录

用于记录一次上下文准备过程，包括任务、返回文档、读取事件、推荐分数、原因和反馈。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 推荐反馈

用于标记推荐文档是否 useful、unnecessary、stale 或 missing，帮助后续判断上下文质量。

细节参考：

- [业务功能说明](./BUSINESS_FEATURES.md)
- [链路流转速查](./FRONTEND_BACKEND_FLOW.md)

### 前端面板

用于查看项目、文档、trace、反馈和整体指标；当前主要是审计和查看用途。

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
