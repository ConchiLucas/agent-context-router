# 读取完整文档

本文件说明 `ctx read` 的使用方式。

## 定位

`ctx read <doc-id>` 是 Context Router 的主流程命令，用来读取文档树中的下一层或具体说明文档。

## 命令

```bash
ctx read <doc-id>
```

示例：

```bash
ctx read context-router-routing-guide
ctx read context-router-area-frontend
ctx read word-select-dashboard-web-react-agents-md
```

系统会自动把读取事件挂到当前调用链路；如果没有当前链路，会创建直接读取记录。

## 约束

- 一次只读取当前任务需要的文档。
- 不要为了保险读取所有文档。
- 如果是源码、配置、表结构或日志，优先直接读取项目目录。
