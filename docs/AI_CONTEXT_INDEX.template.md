# AI_CONTEXT_INDEX.md

本文件是 AI 的上下文树索引入口，只列下一层文档和读取命令。

## 使用方式

- 主流程是按 doc-id 运行 `ctx read <doc-id>`。
- 每份文档继续列出自己的下一层文档。
- `ctx prepare` 只在无法判断 doc-id 时兜底使用。

## 下一层文档

| 文档 | 用途 | 命令 |
| --- | --- | --- |
| `<doc-id>` | `<这份文档解决什么问题>` | `ctx read <doc-id>` |

## 兜底检索

```bash
ctx prepare --project <project-slug>
```

## 规则

- 源码、配置、表结构等实时内容可以直接查项目目录，不强制进入 Context Router。
- 稳定说明、项目规则、链路说明优先通过本索引进入。
- 如果文档树缺少合适入口，在最终回复中说明缺口，便于后续补充索引。
