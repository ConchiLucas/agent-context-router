# 子项目入口文档说明

本文件说明如何从大项目进入具体子项目的入口文档。

## 子项目入口是什么

每个子项目可以有自己的 `AGENTS.md` 或 `AI_CONTEXT_INDEX.md`。AI 需要进入某个子项目时，优先读取对应入口文档。

## 下一层文档

| 文档 | 子项目 | 什么时候读 | 命令 |
| --- | --- | --- | --- |
| `rob-english-word-back-agents-md` | rob-english-word-back | 需要进入 Java 后端子项目的稳定入口 | `ctx read rob-english-word-back-agents-md` |
| `rob-english-word-back-ai_context_index-md` | rob-english-word-back | 需要查看 Java 后端子项目的上下文树和细分路由 | `ctx read rob-english-word-back-ai_context_index-md` |
| `rob-english-word-cloze-web-agents-md` | rob-english-word-cloze-web | 需要进入 Cloze React Web 子项目的稳定入口 | `ctx read rob-english-word-cloze-web-agents-md` |
| `rob-english-word-cloze-web-ai_context_index-md` | rob-english-word-cloze-web | 需要查看 Cloze React Web 子项目的上下文树和细分路由 | `ctx read rob-english-word-cloze-web-ai_context_index-md` |
| `rob-english-word-front-agents-md` | rob-english-word-front | 需要进入 Vue 前端子项目的稳定入口 | `ctx read rob-english-word-front-agents-md` |
| `rob-english-word-front-ai_context_index-md` | rob-english-word-front | 需要查看 Vue 前端子项目的上下文树和细分路由 | `ctx read rob-english-word-front-ai_context_index-md` |
| `word-agent-agents-md` | word-agent | 需要进入 Python agent 服务的稳定入口 | `ctx read word-agent-agents-md` |
| `word-agent-ai_context_index-md` | word-agent | 需要查看 Python agent 服务的上下文树和细分路由 | `ctx read word-agent-ai_context_index-md` |
| `word-select-dashboard-agents-md` | word-select-dashboard | 需要进入 Dashboard 工作区的稳定入口 | `ctx read word-select-dashboard-agents-md` |
| `word-select-dashboard-ai_context_index-md` | word-select-dashboard | 需要查看 Dashboard 工作区的上下文树和细分路由 | `ctx read word-select-dashboard-ai_context_index-md` |
| `word-select-dashboard-server-agents-md` | word-select-dashboard-server | 需要进入 Dashboard 后端服务的稳定入口 | `ctx read word-select-dashboard-server-agents-md` |
| `word-select-dashboard-server-ai_context_index-md` | word-select-dashboard-server | 需要查看 Dashboard 后端服务的上下文树和细分路由 | `ctx read word-select-dashboard-server-ai_context_index-md` |
| `word-select-dashboard-web-react-agents-md` | word-select-dashboard-web-react | 需要进入 Dashboard React 前端的稳定入口 | `ctx read word-select-dashboard-web-react-agents-md` |
| `word-select-dashboard-web-react-ai_context_index-md` | word-select-dashboard-web-react | 需要查看 Dashboard React 前端的上下文树和细分路由 | `ctx read word-select-dashboard-web-react-ai_context_index-md` |

## 使用建议

- 先读目标子项目的 `AGENTS.md`。
- 需要更细路由时，再读该子项目的 `AI_CONTEXT_INDEX.md`。
- 子项目源码、配置和表结构按需直接读取项目目录。
