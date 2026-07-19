# 子项目总览: rob-english-word-workforce

本文件是第二层文档，只介绍大项目下各子项目的职责。具体结构、接口、表、页面和调用链以后拆到第三层文档。

## 子项目清单

| 子项目 | 简要作用 | 第三层文档 |
| --- | --- | --- |
| `rob_english_word_back` | Java 后端服务，提供登录注册、单词、错词、掌握词、游戏匹配、完形填空练习和 WebSocket 对战能力。 | `ctx read rob-english-word-back-overview` |
| `rob_english_word_front` | Vue 主前端，承载登录注册、抢词游戏、答题记录、错词和已掌握单词等用户侧页面。 | `ctx read rob-english-word-front-overview` |
| `rob_english_word_cloze_web` | React 完形填空前端，面向句子完形填空练习、答题和复习体验。 | `ctx read rob-english-word-cloze-web-overview` |
| `word_select_dashboard/server` | Go 后端服务，支撑单词库、句子、AI 配置、执行任务、完形结果和后台管理接口。 | `ctx read word-select-dashboard-server-overview` |
| `word_select_dashboard/web-react` | React 后台页面，用于管理单词库、句子生成、AI 配置、任务执行记录和相关运营功能。 | `ctx read word-select-dashboard-web-react-overview` |
| `word_select_dashboard/word-agent` | Python agent 服务，负责句子生成、任务执行回调、MiMo TTS 音频生成和句子评分。 | `ctx read word-agent-overview` |
| `scripts` | 辅助脚本目录，目前主要包含 MiMo TTS 相关脚本。 | `ctx read rob-english-word-scripts-overview` |

## 第三层规划

后续如果需要深入某个子项目，再为该子项目新增第三层详情文档；本文件不展开实现细节。
