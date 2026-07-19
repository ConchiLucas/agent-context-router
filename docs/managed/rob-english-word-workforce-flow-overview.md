# 项目链路流转: rob-english-word-workforce

本文件是二层链路总览，只说明几个子项目如何协作流转。具体接口、表结构、页面实现和任务细节请按需直接查看项目目录。

## 总体关系

`rob-english-word-workforce` 由用户侧学习应用、后台管理系统和 AI 任务执行服务组成：

- 用户侧前端负责学习、抢词游戏和完形填空页面。
- Java 后端负责用户侧核心 API、WebSocket 对战和 `rob_english_word` 业务数据。
- React 后台和 Go server 负责运营管理、执行任务、AI 配置和结果查看。
- Python word-agent 负责 AI 句子生成、TTS、评分等异步能力。

## 主要流转

| 场景 | 链路 | 结果落点 |
| --- | --- | --- |
| 抢词游戏和用户学习 | `rob_english_word_front` -> `rob_english_word_back` -> PostgreSQL/Redis | 用户、单词、房间、对战、答题和学习状态数据 |
| 实时对战 | `rob_english_word_front` -> WebSocket -> `rob_english_word_back` | Redis 维护房间/临时状态，PostgreSQL 保存最终记录 |
| 完形填空练习 | `rob_english_word_cloze_web` -> `rob_english_word_back` -> `rob_english_word` | 完形题、答题记录、复习和统计数据 |
| 后台管理 | `word_select_dashboard/web-react` -> `word_select_dashboard/server` -> PostgreSQL | 单词库、句子、AI 配置、执行流和运营数据 |
| AI 任务执行 | `word_select_dashboard/server` -> `word_select_dashboard/word-agent` -> 回写/回调 server | 句子生成、TTS、评分和任务事件 |
| 完形结果查看 | `word_select_dashboard/web-react` -> `word_select_dashboard/server` -> `rob_english_word` | 后台查看用户完形答题结果和错题情况 |

## 排查入口

- 用户侧学习或游戏问题：先看 `rob_english_word_front` 页面，再看 `rob_english_word_back` API/WebSocket，最后查 `rob_english_word` 和 Redis。
- 完形练习问题：先看 `rob_english_word_cloze_web`，再看 `rob_english_word_back` 的 `/api/cloze-practice/*` 相关接口，最后查完形相关表。
- 后台管理问题：先看 `word_select_dashboard/web-react`，再看 `word_select_dashboard/server`，最后查 `select_english_word` 或相关业务库。
- AI 生成、TTS 或评分问题：先看 `word_select_dashboard/server` 的任务记录，再看 `word-agent` 日志和回调，最后查生成结果表。

## 相关二层文档

- 子项目职责：`ctx read rob-english-word-workforce-subprojects-overview`
- 数据库连接：`ctx read rob-english-word-workforce-database-info`
