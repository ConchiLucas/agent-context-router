# 开发细节目录

本目录用于存放代码开发相关细节。上一级按需索引见 `../DEVELOPMENT_OUTLINE.md`。

## 文档树

- [功能开发记录](./FEATURE_NOTES.md)：记录新功能或已有功能改造的代码层面内容。
- [Bug 排查记录](./BUG_INVESTIGATIONS.md)：记录非显而易见的 bug 根因、排查过程和修复方式。
- [架构决策记录](./ARCHITECTURE_DECISIONS.md)：记录影响后续开发的技术决策和取舍。
- [代码变更记录](./CODE_CHANGE_LOG.md)：记录跨模块、数据结构、接口 contract 等重要变更。

## 使用规则

- 只记录代码层面的开发信息，不记录普通聊天。
- 简短结论可同步到 `../DEVELOPMENT_OUTLINE.md` 的“当前重要开发结论”。
- 具体过程、背景、长说明写入本目录对应文档。
- 单个主题内容较长时，在本目录下新建独立 Markdown 文件。
- 新增独立细节文档后，需要回到 `../DEVELOPMENT_OUTLINE.md` 添加索引。
