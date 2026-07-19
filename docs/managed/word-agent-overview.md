# 项目概览: word_select_dashboard/word-agent

## 作用用途

`word_select_dashboard/word-agent` 是 Python agent 服务，承担 AI 辅助任务执行、句子生成、TTS 和评分等后端能力。

## 主要功能

- 接收 Go server 发起的异步执行任务，并把步骤事件回调给 Go。
- 根据词汇生成英文例句。
- 调用 MiMo TTS 生成单词或句子的语音文件。
- 对生成句子进行评分，并把评分结果写回业务数据。
- 复用 Go server 的 AI 配置，使 Python 和 Go 使用统一模型设置。

## 适合什么时候读

需要理解 AI 任务由谁执行、句子生成/TTS/评分在哪里完成，或排查 Go 与 Python agent 协作时读本文件。
