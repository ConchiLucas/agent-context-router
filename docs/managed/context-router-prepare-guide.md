# 兜底检索说明

本文件说明什么时候使用 `ctx prepare`。它不是主路径，主路径是按文档树使用 `ctx read <doc-id>`。

## 适用场景

- 总入口和下一层文档都没有明确命中当前任务。
- 不知道应该读哪个 doc-id。
- 需要让系统根据 project、area 和关键词临时推荐文档。

## 命令

```bash
ctx prepare --project <project>
```

明确 area 时：

```bash
ctx prepare --project <project> --area <area>
```

## 返回内容

- 推荐文档列表。
- 每份文档的摘要和匹配原因。
- 后续读取命令：`ctx read <doc-id>`。

拿到 doc-id 后，仍然回到 `ctx read <doc-id>` 读取具体文档。
