# AI_CONTEXT_INDEX.md

本文件是 `rob-english-word-workforce` 的总入口文档。AI 从 `AGENTS.md` 进入这里后，再按本文件选择下一层文档。

本文件中的 `$CTX` 来自 `AGENTS.md`：

```bash
CTX="/Users/conchi/workforce/python_workforce/agent-context-router/bin/ctx"
```

本文件中的 `$SESSION_ID` 是同一个 AI 对话窗口固定复用的 session id。

## 项目大纲

- `startup`：启动、重启、构建、测试、本地验证、Docker Compose。
- `database`：数据库连接、建库、migration、数据检查。
- `frontend`：页面、组件、弹窗、样式、浏览器自测。
- `backend`：API、检索、trace、CLI、MCP、服务逻辑。
- `business`：项目目的、业务功能、上下文使用规则、文档边界。
- `debugging`：bug、异常、调用链、历史改动、缺失上下文。

## 链路总览

```text
AGENTS.md
  -> "$CTX" read rob-english-word-workforce-ai_context_index-md --session "$SESSION_ID"
    -> 使用方式文档
    -> 任务路由文档
      -> area 文档
    -> 子项目入口文档
      -> 子项目 AGENTS.md / AI_CONTEXT_INDEX.md
```

Context Router 会根据 `--session` 在后台自动记录 read 调用链路。AI 不需要手动传 `traceId` 或 `reason`。

## 如何继续阅读

后续读取任意下一层文档时，必须复用同一个 session：

```bash
"$CTX" read <doc-id> --session "$SESSION_ID"
```

## 下一层文档

| 分组 | 文档 | 什么时候读 | 命令 |
| --- | --- | --- | --- |
| 使用方式 | `context-router-usage-guide` | 需要理解 Context Router 的总体使用原则 | `"$CTX" read context-router-usage-guide --session "$SESSION_ID"` |
| 读取规则 | `context-router-read-guide` | 已有 doc-id，需要确认 `ctx read` 使用边界 | `"$CTX" read context-router-read-guide --session "$SESSION_ID"` |
| 调用痕迹 | `context-router-trace-guide` | 需要理解后台如何自动记录调用痕迹 | `"$CTX" read context-router-trace-guide --session "$SESSION_ID"` |
| 任务路由 | `context-router-routing-guide` | 需要按任务类型选择 area 文档 | `"$CTX" read context-router-routing-guide --session "$SESSION_ID"` |
| 子项目入口 | `context-router-project-entry-guide` | 需要进入具体子项目入口文档 | `"$CTX" read context-router-project-entry-guide --session "$SESSION_ID"` |

## 任务路由直达

如果任务类型已经明确，可以直接读取对应 area 文档：

| area | 适用任务 | 命令 |
| --- | --- | --- |
| `startup` | 启动、重启、构建、测试、本地验证、Docker Compose | `"$CTX" read context-router-area-startup --session "$SESSION_ID"` |
| `database` | 数据库连接、建库、migration、数据检查 | `"$CTX" read context-router-area-database --session "$SESSION_ID"` |
| `frontend` | 页面、组件、弹窗、样式、浏览器自测 | `"$CTX" read context-router-area-frontend --session "$SESSION_ID"` |
| `backend` | API、检索、trace、CLI、MCP、服务逻辑 | `"$CTX" read context-router-area-backend --session "$SESSION_ID"` |
| `business` | 项目目的、业务功能、上下文使用规则、文档边界 | `"$CTX" read context-router-area-business --session "$SESSION_ID"` |
| `debugging` | bug、异常、调用链、历史改动、缺失上下文 | `"$CTX" read context-router-area-debugging --session "$SESSION_ID"` |

## 子项目入口

需要进入具体子项目时，先读子项目入口说明：

```bash
"$CTX" read context-router-project-entry-guide --session "$SESSION_ID"
```

这个文档会继续列出各子项目的 `AGENTS.md` 和 `AI_CONTEXT_INDEX.md` doc-id。

## 兜底检索

只有无法判断文档路径时才使用兜底检索：

```bash
"$CTX" read context-router-prepare-guide --session "$SESSION_ID"
```

源码、配置、日志、实时表结构和临时排查信息可以直接读取项目目录，不需要进入受管文档。
