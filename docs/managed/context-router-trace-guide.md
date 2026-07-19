# 调用痕迹记录

本文件说明 trace 在 Context Router 中的作用。

## trace 记录什么

- AI 通过 `ctx read` 读取了哪些文档。
- AI 通过 `ctx prepare` 兜底检索时返回了哪些文档。
- 哪些推荐文档被读取，哪些只是被返回。
- 后续反馈中标记的 useful、missing、stale、unnecessary。

## 对 AI 的要求

AI 只需要执行：

```bash
ctx read <doc-id>
```

或在无法判断 doc-id 时执行：

```bash
ctx prepare --project <project>
```

系统会在命令/API 封装层内部串起调用链路，AI 不需要手动传 traceId 或 reason。
