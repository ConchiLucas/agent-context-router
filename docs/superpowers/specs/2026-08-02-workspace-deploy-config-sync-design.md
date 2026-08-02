# Workspace Deploy 配置同步设计

## 目标

把目标 Workspace 仓库内的 `deploy/context-router/` 文件作为运行配置唯一事实源。Context Router 只负责扫描、校验、预览并将完整配置原子同步到 PostgreSQL；即使 Context Router 不可用，仓库里的 `deploy.sh` 和 `AGENTS.md` 仍能指导本机 AI 直接启动项目。

## 目录契约

Workspace 根目录保存清单和 Workspace 启动入口：

```text
deploy/context-router/
├── manifest.yaml
├── README.md
└── workspace/start/
    ├── deploy.sh
    └── ...
```

每个已登记 Project 在自己的项目根目录保存两个运行模式：

```text
<project-root>/deploy/context-router/
├── fast/
│   ├── deploy.sh
│   └── ...
└── full/
    ├── deploy.sh
    └── ...
```

`manifest.yaml` 固定使用版本化格式：

```yaml
schema_version: 1
workspace:
  workspace_paths:
    - deploy
    - docker-compose.yml
project_order:
  - backend
  - frontend
```

`project_order` 使用 Project 相对 Workspace 的路径。同步服务根据相对路径解析当前数据库 Project ID；不把数据库 UUID 或由绝对路径哈希得到的 `project_key` 写入仓库。

## 扫描与校验

服务端只扫描固定位置，API 不接收任意源路径。预览和提交共同使用同一个扫描器：

- `manifest.yaml` 必须存在，`schema_version` 必须是 `1`。
- `project_order` 必须与当前 Workspace 已登记 Project 一一对应，不允许遗漏、重复或未知路径。
- Workspace `start` 及每个 Project 的 `fast`、`full` 目录必须存在并包含可执行的 `deploy.sh`。
- 文件必须是 Workspace 内的普通 UTF-8 文本文件；拒绝软链接、绝对路径、路径穿越和越界解析。
- 拒绝 `.env.local`、私钥、证书私钥和常见秘密文件名；允许 `.env.example` 一类模板。
- 沿用当前运行配置限制：每个 profile 最多 100 个文件，单文件最多 1 MB。
- YAML 文件在预览阶段完成语法校验。

扫描结果生成规范化 SHA-256 摘要。预览返回摘要和与数据库当前状态的新增、修改、删除统计。提交必须携带预览摘要，服务端重新扫描；若文件已变化，返回冲突并要求重新预览。

## 原子同步

提交成功前不删除任何旧数据。PostgreSQL 仓储在同一个数据库事务中完成：

1. 替换 Workspace `start` 文件；
2. 替换 Workspace runtime policy；
3. 替换 Workspace 下所有 Project 的 `fast` 和 `full` 文件；
4. 删除本次完整集合之外、但属于该 Workspace Project 的旧 runtime 文件。

任一步异常都回滚整个事务。内存仓储使用加锁后的副本交换提供同等的 all-or-nothing 语义，便于 API 和服务测试。

## API 与管理界面

新增两个固定 POST 接口：

- `POST /api/workspaces/{workspace_id}/runtime-config/sync-preview`
- `POST /api/workspaces/{workspace_id}/runtime-config/sync`

提交体仅包含 `expected_digest`，不允许指定扫描目录。浏览器只读中间件只为这两个精确路径增加白名单。

Workspace 详情页增加“同步 deploy 配置”按钮。点击后先显示扫描来源、各 profile 文件数、增删改统计和校验错误；仅有效预览允许确认同步。同步成功后显示新摘要和更新时间，失败时保留旧数据库配置并展示错误。

## 独立运行兼容

同步器不重写仓库文件。每个 `deploy.sh` 必须自行定位脚本目录和 Workspace/Project 根目录；`WORKSPACE_HOST_ROOT`、`PROJECT_HOST_ROOT` 只作为 Context Router 执行时的可选覆盖值。Workspace 根 `AGENTS.md` 应链接 `deploy/context-router/README.md` 并给出不依赖 Router 的直接启动命令。

## 测试范围

- 扫描有效目录并解析相对路径顺序；
- 拒绝缺少 profile、不可执行入口、未知 Project、秘密文件、软链接和路径越界；
- 预览摘要变化时提交返回冲突；
- 仓储中途失败时旧 Workspace/Project 配置不变；
- 浏览器仅能调用两个同步 POST，其他管理写接口仍返回 405；
- 前端 API、按钮、预览、确认、错误和成功状态；
- Docker Compose 内运行后端测试、前端测试、lint 和构建。
