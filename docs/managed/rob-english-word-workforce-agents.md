# AGENTS.md

本文件是 `rob-english-word-workforce` 在 Context Router 中的一级入口索引。

## 下一层文档

| 文档 | 什么时候读 | 命令 |
| --- | --- | --- |
| `rob-english-word-workforce-subprojects-overview` | 需要先了解大项目下有哪些子项目，以及每个子项目大概做什么 | `ctx read rob-english-word-workforce-subprojects-overview` |
| `rob-english-word-workforce-database-info` | 需要连接 PostgreSQL/Redis、确认库名账号端口或排查数据库数据问题 | `ctx read rob-english-word-workforce-database-info` |
| `rob-english-word-workforce-flow-overview` | 需要了解用户侧、后台、Java 后端、Go server 和 Python agent 之间如何流转 | `ctx read rob-english-word-workforce-flow-overview` |

## 说明

这里只保留下一层入口，不放具体业务细节。第二层文档按主题给出简要入口；需要展开的主题再拆第三层，不需要展开的主题直接作为叶子节点。

## 规则

- 后续所有 Context Router 调用都复用同一个 `$SESSION_ID`。
- 源码、配置、日志、实时表结构和临时排查信息可以直接读取项目目录。
