# 业务功能路由

本文件用于把产品能力、业务规则和用户工作流类任务路由到合适上下文。

## 适用任务

- 询问这个系统的用途。
- 新增或调整项目管理、文档管理、上下文准备、trace、反馈等功能。
- 梳理 AI 如何按需读取上下文。
- 判断某个文档是否应该进入受管文档库。

## 子路由

- `project_management`：项目和子项目层级。
- `document_management`：稳定文档、入口索引和全文读取。
- `context_workflow`：prepare/read/trace 的用户流程。
- `observability`：后台如何观察 AI 使用了哪些文档。

## 下一层文档

| 文档 | 用途 | 命令 |
| --- | --- | --- |
| `context-router-usage-guide` | Context Router 使用规则 | `ctx read context-router-usage-guide` |
| `context-router-routing-guide` | 文档树路由规则 | `ctx read context-router-routing-guide` |
| `context-router-project-entry-guide` | 子项目入口说明 | `ctx read context-router-project-entry-guide` |

业务文档只保存稳定意图和规则，源码、配置和临时实现细节按需直接读取项目目录。
