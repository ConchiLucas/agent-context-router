# 代码变更记录

本文件用于记录跨模块、数据结构、接口 contract、工程约定等重要代码变更。

## 记录规则

- 按日期追加记录。
- 只记录代码层面的开发信息，不记录普通聊天。
- 简要结论可同步到 `../DEVELOPMENT_OUTLINE.md`。
- 如果内容影响启动、数据库、业务功能或链路流转，需要同步更新对应文档。

## 记录

### 2026-06-27

- 建立 `docs/DEVELOPMENT_OUTLINE.md` 作为代码开发大纲。
- 新建 `docs/development-details/` 目录，用于按类型存放开发细节。
- 根目录 `AGENTS.md` 保留一级索引，开发细节通过大纲按需读取。
- 移除文档切分功能：后端删除 `DocumentChunk`、`document_chunks`、`chunk_id/chunk_count` 和 `chunking.py`；检索改为直接使用 `documents.content_markdown`；前端移除 Chunks 展示；新增 migration `20260627_0003_remove_document_chunks`。
