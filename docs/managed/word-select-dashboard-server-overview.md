# 项目概览: word_select_dashboard/server

## 作用用途

`word_select_dashboard/server` 是单词清洗和后台管理体系的 Go 后端，负责管理后台 API、任务状态、AI 配置和数据持久化。

## 主要功能

- 提供单词库、清洗单词、句子、完形结果和用户相关后台接口。
- 管理 AI provider/model 配置，供前端和 Python agent 使用。
- 记录执行任务、工作流状态和系统事件。
- 对接 Python word-agent，触发句子生成、评分、TTS 等异步任务。
- 使用 Gin/Gorm 等 Go 后端基础设施，支撑多数据库配置和后台服务运行。

## 适合什么时候读

需要理解后台管理 API、单词清洗任务、AI 配置或 Go 服务在整个系统中的位置时读本文件。
