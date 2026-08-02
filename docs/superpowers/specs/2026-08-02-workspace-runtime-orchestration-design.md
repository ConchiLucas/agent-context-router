---
title: Workspace 运行编排与宿主机 Runtime Runner 技术方案
summary: 定义 Codex、Context Router、宿主机 Runner、目标工作空间与本机配置之间的边界，以及增量更新和全量启动的统一 MCP 流程。
---

# Workspace 运行编排与宿主机 Runtime Runner 技术方案

## 1. 背景

Context Router 已具备 Workspace/Project 路由、项目级快速与完整运行配置、配置快照物化、异步运行记录，以及以下项目级 MCP 工具：

- `apply_project_changes`
- `get_project_operation`

当前执行线程位于 Context Router 后端容器内，适合调用 Docker CLI，但无法完整承担目标工作空间中的宿主机能力。例如英语单词工作空间的全量入口除六个 Docker Project 外，还会使用 macOS `zsh`、`launchctl`、宿主机 Python 环境以及本机 Codex/Gemini CLI 启动 CLI Runner。

目标是让所有注册到 Context Router 的 Workspace 获得统一效果：

1. Codex 在任意 Project 目录完成代码修改和验证后，通过 MCP 提交实际改动文件。
2. Context Router 自动识别受影响 Project，并选择快速或完整更新。
3. 用户在 Workspace 任意目录表达“启动”意图时，统一启动该 Workspace 注册的全部项目。
4. Context Router 负责编排、授权、状态和审计，宿主机 Runner 只负责执行已登记的固定脚本。
5. 每个目标 Workspace 保留根 `.env.local` 作为当前电脑唯一的数据库、Redis、MinIO 等私有运行配置入口。

## 2. 已确认的产品规则

### 2.1 启动语义

在已注册 Workspace 范围内，只要用户明确要求“启动”“启动项目”“启动服务”或“启动全部项目”，Codex 就调用 Workspace 全量启动工具。系统不推断部分启动，也不在 MCP 层暴露模糊的单项目启动语义。

全量启动不因“首次”“联调”或“完整验证”等上下文而分支。一个 Workspace 只登记一个正式全量入口，由目标 Workspace 自己负责依赖顺序、预检、构建、健康检查和幂等行为。

系统不会因为新建 Codex 任务而自动启动 Workspace。启动必须来自用户明确的启动意图。

### 2.2 修改后更新语义

Codex 完成代码修改并执行相关验证后，把本次实际修改的 Workspace 相对路径提交给 Context Router。Context Router 负责文件归属和更新模式判断：

- 普通业务源码、静态资源和非构建配置：快速更新。
- 依赖清单、锁文件、Dockerfile、Compose、构建器配置：完整更新。
- 同时修改多个 Project：按 Project 分组并创建一个 Workspace 父操作。
- Workspace 根运行入口或统一运行配置结构变化：执行 Workspace 全量启动配置。

这不是文件监听器。Context Router 不在每次保存文件时部署；交互由 Codex 在任务验证阶段主动发起。

### 2.3 本机配置语义

每个目标 Workspace 根保留：

```text
.env.example  # Git 跟踪，定义统一字段
.env.local    # Git 忽略，保存当前电脑真实值
```

`.env.local` 由目标 Workspace 的部署脚本读取。Context Router、MCP 参数、运行任务数据库和 Agent 文档均不保存或返回其内容。

### 2.4 启动 Context Router

本方案不提供 Context Router 开机自启动，不配置 Docker Desktop 登录启动，也不配置用于 Context Router 的 launchd 任务。用户按需手动启动 Context Router 和宿主机 Runner。

Context Router 未运行时，MCP 不可用；MCP 不能启动自身。Codex 必须明确报告此状态，不绕过统一编排假装任务已经执行。

## 3. 设计原则与边界

| 组件 | 主导职责 | 明确不负责 |
| --- | --- | --- |
| 用户 | 发出修改、验证或启动意图；决定是否允许破坏性操作 | 不提供 Project ID、脚本路径或更新模式 |
| Codex | 读取规则、修改与验证代码、调用 MCP、轮询最终状态 | 不自行判断 Project ID，不拼接部署命令，不回显私密配置 |
| Workspace 根 `AGENTS.md` | 规定什么时候调用统一 MCP 工作流 | 不保存机器连接值，不复制 Runtime 脚本，不实现执行逻辑 |
| Project `AGENTS.md` | 项目特有测试、迁移、构建前置条件 | 不重复 Workspace 通用编排规则 |
| Context Router | Workspace/Project 解析、模式选择、任务编排、配置快照、状态聚合、日志与审计 | 不修改业务源码，不读取目标 `.env.local`，不执行 Agent 传入的任意命令 |
| 宿主机 Runtime Runner | 领取已授权任务、验证快照、执行固定入口、上报心跳与结果 | 不决定执行哪个 Workspace/Project，不决定更新模式，不接收任意 Shell 字符串 |
| 目标 Workspace | 定义全量入口、项目快速/完整部署脚本和健康检查 | 不实现 Context Router 的通用任务编排 |

能力适用范围是“注册到 Context Router 且完成运行配置的 Workspace”，不是磁盘上任意目录。

## 4. 总体架构

```text
User
  │ intent
  ▼
Codex in registered Workspace
  │ MCP: prepare / apply_workspace_changes / start_workspace / get_workspace_operation
  ▼
Context Router control plane
  ├─ Workspace + Project registry
  ├─ runtime policy and file classification
  ├─ immutable configuration materialization
  ├─ operation state machine and audit
  └─ host job lease API
         │ authenticated lease / heartbeat / completion
         ▼
Host Runtime Runner
  ├─ validates allowed roots and snapshot manifest
  ├─ executes only materialized deploy.sh
  ├─ reads target Workspace .env.local indirectly through its script
  └─ writes bounded log and final exit status
         │
         ▼
Target Workspace scripts → Docker Desktop / macOS CLI Runner / health checks
```

控制面和执行面分离：Context Router 是唯一决策者，宿主机 Runner 是无业务判断的执行适配器。

## 5. Agent 发现与行为规则

### 5.1 MCP 连接发现

希望所有本机 Codex Workspace 都能使用 Context Router 时，在用户级配置一次：

```toml
[mcp_servers.context_router]
url = "http://127.0.0.1:49173/mcp"
enabled = true
```

项目级 `.codex/config.toml` 只用于需要隔离接入范围的特殊仓库，不作为默认方案。

### 5.2 Workspace 根规则

每个受管 Workspace 根 `AGENTS.md` 增加一段简短且稳定的统一规则：

```markdown
## Context Router 运行规则

- 新任务开始时调用 `prepare_task_context`，保存返回的 `task_id`。
- 用户明确要求启动时调用 `start_workspace(task_id)`，启动当前 Workspace 全部项目。
- 修改源码并完成项目规定的验证后，提交本次实际改动路径到
  `apply_workspace_changes(task_id, changed_files)`。
- 调用 `get_workspace_operation(operation_id)`，等待操作进入最终状态后再报告结果。
- 失败时报告失败步骤和日志，不删除容器、镜像、卷或业务数据。
- MCP 或宿主机 Runner 不可用时明确报告，不绕过统一入口执行另一套部署流程。
```

Context Router 的 MCP Server instructions 同步包含上述通用约定，作为所有客户端的中央兜底。根 `AGENTS.md` 负责在目标 Workspace 中明确采用该约定；Project 文档只声明例外和前置条件。

`AGENTS.md` 是行为契约，不是强制钩子。系统不会监视 Agent 是否编辑过文件。强制执行边界位于 MCP 工具内部：一旦调用，路径归属、运行配置、执行入口和状态转换均由服务端验证。

## 6. MCP 工具契约

### 6.1 `apply_workspace_changes`

目的：把一个 Codex 任务中的实际改动路由到一个或多个 Project，并执行相应更新。

输入：

```json
{
  "task_id": 123,
  "changed_files": [
    "rob_english_word_back/src/main/java/example/UserService.java",
    "rob_english_word_front/src/views/Home.vue"
  ]
}
```

约束：

- `task_id` 必须是当前 `prepare_task_context` 返回的有效 Workspace task。
- `changed_files` 为 1 至 500 个 Workspace 相对 POSIX 路径，每项最多 1000 字符。
- 禁止绝对路径、空路径、反斜杠、NUL、`.` 和 `..` 路径段。
- 解析后的真实路径必须保留在 task 绑定的 Workspace 根内；软链接不得越界。
- 重复路径规范化后去重，响应保持稳定排序。

路由规则：

1. 使用 task 快照解析当前 Workspace。
2. 以 Project 源码 `relative_path` 最长前缀匹配每个文件；嵌套 Project 优先。
3. 根 Project `relative_path='.'` 只接收未被更深 Project 匹配的文件。
4. 未归属任何 Project 的普通业务文件返回 `unmapped_changed_file`，不静默忽略。
5. Workspace 级部署文件、根 `.env.example` 或登记的全量入口变化，路由为 Workspace `start` 步骤。
6. 每个 Project 内只要一个文件命中完整更新集合，该 Project 整体使用 `full`，否则使用 `fast`。

输出：

```json
{
  "operation_id": "32-char-id",
  "workspace_id": "workspace-id",
  "kind": "apply_changes",
  "status": "queued",
  "steps": [
    {
      "project_id": "project-id",
      "mode": "fast",
      "changed_files": ["..."],
      "decision_reason": "仅业务代码或资源文件发生变化"
    }
  ]
}
```

工具立即返回，不等待执行完成。MCP annotations 使用 `readOnlyHint=false`、`destructiveHint=true`、`idempotentHint=false`、`openWorldHint=false`。

### 6.2 `start_workspace`

目的：启动 task 绑定 Workspace 的全部项目。

输入：

```json
{
  "task_id": 123
}
```

服务端只使用 task 绑定的 Workspace，不接受客户端提供 Workspace ID、根路径、脚本路径或命令。一个 Workspace 同时只能存在一个非最终状态的 `start_workspace` 操作。

服务端读取 Workspace `start` 运行配置，要求存在固定入口 `deploy.sh`，物化不可变快照并创建一个 Workspace 步骤。目标 Workspace 的 `deploy.sh` 负责调用该 Workspace 正式全量入口。例如英语单词 Workspace 的包装脚本只调用根 `deploy-compose-full.sh`。

输出包含 `operation_id`、Workspace 元数据、`queued` 状态、配置快照摘要和创建时间，不返回脚本正文、`.env.local` 或绝对私密配置。

工具同样为异步、非幂等、具有破坏性提示。目标启动脚本本身应尽量幂等，但重复 MCP 调用仍创建独立审计记录。

### 6.3 `get_workspace_operation`

目的：查询 `apply_workspace_changes` 或 `start_workspace` 创建的父操作及有界日志。

输入：

```json
{
  "operation_id": "32-char-id",
  "log_characters": 10000
}
```

输出包含：

- 操作类型、Workspace 和创建来源。
- 父状态、当前步骤和总进度。
- 每个 Project/Workspace 步骤的模式、状态、退出码和客观错误摘要。
- 最多 50,000 字符的日志尾部及 `truncated` 标记。
- 创建、领取、开始、完成和最后心跳时间。

该工具不要求 `task_id`，因为不可猜测的 operation ID 是查询句柄；服务端仍按 operation 记录的 task/workspace 关系返回固定范围。它是只读、幂等工具。

### 6.4 兼容工具

现有 `apply_project_changes` 和 `get_project_operation` 保留一个兼容周期：

- `apply_project_changes` 内部转换为单 Project Workspace 操作，不再直接启动容器线程。
- `get_project_operation` 从对应步骤投影旧响应。
- MCP 描述标记为兼容接口，新 Agent instructions 只推荐 Workspace 工具。
- 兼容期结束前不删除旧运行记录或页面历史。

## 7. 文件归属与模式选择

### 7.1 完整更新文件集合

沿用并集中维护现有完整更新判断：

- Maven/Gradle 构建文件。
- Go module 文件。
- Python 项目与锁文件。
- Node package 与锁文件。
- Dockerfile 及变体。
- Compose 文件。
- `.mvn/`、`gradle/` 等构建器目录。

文件集合属于 Context Router 通用代码，不复制到 Workspace 文档。

### 7.2 Workspace 级文件

Workspace 运行策略显式登记以下路径集合：

- 全量启动入口，例如 `deploy-compose-full.sh`。
- 根运行配置模板，例如 `.env.example`。
- 被全量入口直接加载的公共脚本目录或明确文件。

这些文件变化时，`apply_workspace_changes` 创建 Workspace `start` 步骤，而不是猜测一个 Project。

`.env.local` 默认不应由 Codex 修改，也不会出现在 Git 改动列表。若用户明确要求修改并把该路径传入，服务端只记录“本机运行配置变化”的脱敏原因，不保存文件内容，并选择 Workspace `start`。

### 7.3 多 Project 执行顺序

Workspace 保存一个可选的 Project 更新顺序，只引用当前 Workspace 的 Project ID。未配置时使用稳定默认顺序：后端 Project 在前、前端 Project 在后，同类按 `relative_path` 排序。

第一阶段串行执行步骤，避免多个 Docker build 和端口替换同时争用本机资源。未来需要并行时再增加显式并发上限和依赖图，不在本方案第一阶段实现。

任一步骤失败后，剩余步骤标记 `skipped`，父操作为 `failed`。系统不自动回滚或删除已经成功更新的服务，因为容器和数据回滚需要目标 Workspace 自己定义明确策略。

## 8. Workspace 运行配置

### 8.1 数据结构

新增 Workspace 级运行配置，与现有项目级 `fast/full` 文件保持相同安全模型：

```text
workspace_runtime_files
  id
  workspace_id
  profile            # 第一阶段固定 start
  relative_path
  content
  executable
  created_at
  updated_at
```

唯一约束为 `(workspace_id, profile, lower(relative_path))`。每个 `start` 配置必须包含可执行的固定入口 `deploy.sh`。

Workspace 运行策略可使用独立表：

```text
workspace_runtime_policies
  workspace_id
  project_order      # JSONB project ID array
  workspace_paths    # JSONB path array
  updated_at
```

策略只保存路由元数据，不保存数据库、Redis、MinIO连接值。

### 8.2 物化

扩展当前 `RuntimeMaterializationService`，支持：

```text
/runtime/workspaces/{workspace_id}/start/{snapshot_id}/
/runtime/projects/{project_id}/{fast|full}/{snapshot_id}/
```

每个快照继续包含：

- 文件相对路径、权限、大小和 SHA-256。
- 快照 ID、所有者类型与 ID、profile/mode、创建时间。
- canonical manifest SHA-256。

临时目录完整写入并校验后原子重命名，Runner 永远不执行尚未完成的快照。

### 8.3 新 Workspace 接入标准

任何新 Workspace 要获得相同效果，只完成一次声明式接入，不复制 Context Router 代码：

1. 注册 Workspace 根和 Project 源码/文档相对路径。
2. 为每个需要增量更新的 Project 保存 `fast/full` Runtime 配置。
3. 为 Workspace 保存唯一 `start` Runtime 配置及固定 `deploy.sh`。
4. 保存 Workspace 级路径集合和可选 Project 更新顺序。
5. 在 Workspace 根 `AGENTS.md` 声明统一 MCP 工作流。
6. 由目标仓库跟踪 `.env.example`，每台电脑创建 Git 忽略的 `.env.local`。
7. 完成一次 Host Runner 下的配置预检、快速更新、完整更新和全量启动验收。

完成后，Codex 与 MCP 的交互协议在所有 Workspace 中保持一致；项目差异只存在于登记的 Runtime 文件和目标仓库脚本中。

## 9. 操作与步骤数据模型

新增 Workspace 父操作，复用现有项目运行记录作为迁移来源，但新执行统一写入一般化模型。

```text
runtime_operations
  id
  task_id
  workspace_id
  kind                  # apply_changes | start_workspace
  trigger               # mcp | api
  status                # queued | leased | running | succeeded | failed | cancelled | interrupted
  changed_files         # JSONB, normalized paths only
  current_step
  error_code
  error_message
  runner_id
  lease_token_hash
  lease_expires_at
  created_at
  leased_at
  started_at
  finished_at
  last_heartbeat_at

runtime_operation_steps
  id
  operation_id
  sequence
  owner_type             # workspace | project
  owner_id
  mode                   # start | fast | full
  status                 # queued | running | succeeded | failed | skipped | cancelled
  snapshot_id
  snapshot_relative_path
  entry_file             # 固定 deploy.sh
  changed_files          # JSONB
  decision_reason
  log_relative_path
  exit_code
  error_code
  error_message
  started_at
  finished_at

runtime_runner_instances
  id
  hostname
  platform
  version
  capabilities          # JSONB，例如 docker、zsh、launchctl
  status                # online | offline
  started_at
  last_heartbeat_at
```

数据库只保存相对快照和日志路径。容器路径、宿主机路径在各自进程内由配置根安全解析，避免把一个环境的绝对路径当作另一个环境的执行依据。

`runtime_runner_instances` 不保存宿主机环境变量、用户目录内容或认证 token。第一阶段只允许一个 online Runner；表结构保留稳定 Runner 身份和能力检查，避免把“最近有 HTTP 请求”等同于“当前机器具备执行条件”。

## 10. 状态机

父操作状态：

```text
queued → leased → running → succeeded
                         ├→ failed
                         ├→ cancelled
                         └→ interrupted
```

规则：

- `queued`：配置已物化，等待宿主机 Runner。
- `leased`：Runner 已领取，但尚未确认入口启动。
- `running`：Runner 已启动当前步骤并持续心跳。
- `succeeded`：全部步骤退出码为 0。
- `failed`：入口校验失败、任一步骤非零退出、健康检查失败或明确超时。
- `cancelled`：只允许未来的显式取消 API 产生，第一阶段 MCP 不提供取消。
- `interrupted`：Runner/后端重启、租约过期或执行状态无法确认。

租约过期不自动重试破坏性任务。后台把操作收敛为 `interrupted`，由用户重新发起，避免同一 Compose 操作在未知状态下并行执行两次。

## 11. 宿主机 Runtime Runner

### 11.1 进程模型

Runner 是 Context Router 仓库提供的独立宿主机命令，不使用 launchd，不开机自动启动。用户按需运行统一入口：

```bash
./scripts/start-local-stack.sh
```

该入口：

1. 创建或校验共享运行目录和 `runner.token`，再以 `0600` 权限保存。
2. 使用 Docker Compose 启动/恢复 Context Router backend 和 frontend，使后端从共享挂载读取同一 token。
3. 等待 Context Router `/health`。
4. 启动一个当前用户权限的 Host Runner，并保存受控 PID 与日志。
5. 等待 Runner 注册和心跳可见后返回成功。

对应提供 `stop-local-stack.sh` 和 `status-local-stack.sh`。停止脚本只停止通过本仓库标记和 PID 校验的 Runner，不匹配时拒绝发送信号。是否同时停止 Docker Compose 由显式参数控制，默认只停止 Runner。

这是项目“仅使用 Docker Compose 管理前后端”的一个有意例外：业务前后端仍全部由 Compose 管理，Host Runner 因必须调用 macOS 能力而作为受限执行适配器运行在宿主机。

Runner CLI 使用 Python 标准库实现 HTTP、JSON、路径校验、哈希、子进程和信号处理，不导入后端应用包，也不要求从网络安装依赖。它与后端只共享版本化 JSON 协议和运行目录，使冷启动不依赖额外 Python 虚拟环境。

### 11.2 共享运行目录

Compose 已把宿主机 `.runtime-runner` 挂载为后端容器 `/runtime`。新增明确映射：

```text
Host:      {CONTEXT_ROUTER_RUNTIME_HOST_ROOT}
Container: /runtime
```

快照、日志、PID 和 Runner token 均位于此根下。目录权限 `0700`，token、PID 和敏感元数据文件权限 `0600`，日志默认 `0640`。

### 11.3 认证与通信

`start-local-stack.sh` 首次生成高熵 Runner token，写入共享根 `runner.token`。后端只读取 `/runtime/runner.token`，Host Runner 读取宿主机对应文件。数据库不保存明文 token；日志不记录 token。

Runner 通过绑定回环地址的后端 API 通信：

```text
POST /api/runtime-runner/register
POST /api/runtime-runner/heartbeat
POST /api/runtime-runner/lease
POST /api/runtime-runner/operations/{id}/started
POST /api/runtime-runner/operations/{id}/heartbeat
POST /api/runtime-runner/operations/{id}/steps/{step_id}/complete
POST /api/runtime-runner/operations/{id}/complete
```

所有请求使用 `Authorization: Bearer <runner-token>`，服务端使用恒定时间比较。Runner API 不接受浏览器 Origin/Fetch Metadata 请求，不出现在公开管理页面写操作白名单中。

领取操作时服务端额外签发一次性 lease token，只把哈希保存到 operation。后续 started/heartbeat/complete 请求同时携带全局 Runner token 和 lease token，防止旧 Runner 或错误进程更新不属于自己的操作。

Lease 响应只返回：

- operation/step ID。
- owner 类型和稳定 ID。
- Workspace 宿主机根路径。
- 共享运行根下的快照、入口和日志相对路径。
- 超时与 manifest digest。

不返回 Runtime 文件正文、数据库连接值或任意命令数组。

### 11.4 执行前验证

Host Runner 在每个步骤前执行：

1. Workspace 根必须是绝对路径，并位于允许的 `CONTEXT_ROUTER_WORKSPACE_HOST_ROOT` 内。
2. Workspace/Project 当前真实路径与任务快照一致；软链接不得越界。
3. 快照必须位于共享运行根内，不能为符号链接。
4. manifest schema、文件数量、大小和每个 SHA-256 必须匹配。
5. 固定入口只能是快照根下 `deploy.sh`，必须为普通可执行文件。
6. 日志路径必须位于该 operation 专属目录。

验证通过后仅执行：

```text
/bin/sh <validated-snapshot>/deploy.sh
```

Runner 注入受控环境变量：

```text
RUNTIME_OPERATION_ID
RUNTIME_STEP_ID
RUNTIME_DEPLOY_MODE
RUNTIME_SNAPSHOT_DIR
PROJECT_ROOT / PROJECT_HOST_ROOT（Project 步骤）
WORKSPACE_ROOT / WORKSPACE_HOST_ROOT
```

`deploy.sh` 可进入 `WORKSPACE_HOST_ROOT` 并调用目标根脚本。`.env.local` 只在目标脚本进程中读取。

### 11.5 日志与超时

Runner 把 stdout/stderr 合并写入 operation 专属日志，不把完整日志通过 heartbeat 传输。Context Router 从共享目录读取有界尾部。

日志头只记录 operation、step、mode、owner、snapshot ID，不记录进程环境。服务端返回前继续应用现有敏感信息脱敏规则，并限制单次 MCP 最大字符数。

每个步骤使用服务端下发的 10 至 7200 秒超时。超时先向进程组发送 `TERM`，等待 10 秒后发送 `KILL`，记录退出码 124。Runner 停止时不清理目标容器或数据。

## 12. 主要交互流程

### 12.1 手动启动控制面

```text
User → start-local-stack.sh
  → docker compose up -d Context Router
  → wait /health
  → start Host Runner
  → Runner heartbeat visible
  → ready
```

### 12.2 启动整个 Workspace

```text
User: “启动项目”
Codex → prepare_task_context(task, cwd)
Context Router → task_id + Workspace snapshot
Codex → start_workspace(task_id)
Context Router → validate task and runtime config
Context Router → materialize immutable start snapshot
Context Router → create queued operation
Host Runner → lease operation
Host Runner → validate manifest and paths
Host Runner → execute workspace deploy.sh
Target script → read .env.local and start all services
Host Runner → report result
Codex → get_workspace_operation until terminal status
Codex → report exact result to User
```

### 12.3 修改后增量更新

```text
User → asks for code change
Codex → prepare, read context, edit, verify
Codex → collect actual workspace-relative changed files
Codex → apply_workspace_changes(task_id, changed_files)
Context Router → normalize and route files to Projects
Context Router → select fast/full for each Project
Context Router → create ordered steps and snapshots
Host Runner → lease and execute each step serially
Context Router → aggregate status and bounded logs
Codex → poll to terminal status and report
```

## 13. 错误模型

MCP 和内部服务使用稳定错误码，用户文本可以本地化：

| 错误码 | 条件 | 行为 |
| --- | --- | --- |
| `task_not_found` | task 不存在 | 要求重新 prepare |
| `workspace_not_found` | task 的 Workspace 已删除 | 停止，不猜测其他 Workspace |
| `runtime_policy_missing` | Workspace 未配置运行策略 | 返回缺失配置摘要 |
| `runtime_entry_missing` | 快照缺少 `deploy.sh` | 不创建可执行任务 |
| `unmapped_changed_file` | 文件不属于 Project 或 Workspace 级路径 | 返回全部未映射路径 |
| `unsafe_changed_path` | 绝对路径、越界或软链接逃逸 | 拒绝整个调用 |
| `operation_in_progress` | 同一作用域已有活动任务 | 返回现有 operation ID |
| `host_runner_unavailable` | 最近心跳超出阈值 | 不排队或明确返回不可执行状态 |
| `runtime_snapshot_invalid` | manifest 或路径校验失败 | 操作失败，不执行脚本 |
| `runtime_timeout` | 步骤超时 | 终止进程组，后续步骤 skipped |
| `runtime_exit_nonzero` | deploy.sh 非零退出 | 保留环境，返回退出码和日志尾部 |
| `runtime_interrupted` | 租约过期或进程状态未知 | 不自动重试 |

`start_workspace` 在 Host Runner 不可用时直接返回 `host_runner_unavailable`，避免用户误以为全量启动已经排队。`apply_workspace_changes` 使用相同规则。

## 14. 并发与一致性

- 同一 Workspace 最多一个活动 `start_workspace` 操作。
- 同一 Project 最多一个活动更新步骤。
- Workspace 全量启动与该 Workspace 任意 Project 更新互斥。
- 不同 Workspace 可以并发排队，但第一阶段单 Host Runner 仍逐个领取。
- 创建父操作、步骤和租约使用 PostgreSQL 事务与条件更新。
- Lease 使用 `SELECT ... FOR UPDATE SKIP LOCKED`，即使误启动两个 Runner，也不会重复领取同一操作。
- 后端重启后保留 `queued`，但把已 `leased/running` 且租约过期的操作收敛为 `interrupted`。

## 15. 安全边界

1. MCP 从不接受命令、脚本正文、绝对项目路径或环境变量映射。
2. Runtime 配置只能通过本机 AI/运维的受校验 API 保存，浏览器继续只读。
3. Host Runner只执行已物化且 manifest 校验通过的固定 `deploy.sh`。
4. Workspace 和 Project 路径继续使用注册表与最长前缀规则，并校验软链接边界。
5. `.env.local` 不进入 Context Router 数据库、MCP payload、运行摘要或设计文档。
6. Runner API 绑定回环地址并要求共享 token；Context Router 仍不得直接暴露公网。
7. Docker Socket 仍代表宿主机 Docker 管理权限，操作必须保留 MCP destructive annotation 和清晰审计。
8. MCP 和 API 返回日志必须有字符上限、截断标记和敏感信息脱敏。
9. 不自动删除容器、镜像、卷、日志、PID 或业务数据。

## 16. 页面与管理 API

第一阶段页面保持只读，不新增“执行”按钮。可扩展现有运行配置页面：

- Workspace 详情增加只读“全量启动配置”入口。
- Project 页面继续展示 fast/full 文件和历史记录。
- Workspace 页面展示父操作和子步骤聚合状态。
- 日志仍按需读取，不在列表接口内联。

本机 AI/运维 API 增加：

```text
GET /api/workspaces/{workspace_id}/runtime-config
PUT /api/workspaces/{workspace_id}/runtime-config/start
PUT /api/workspaces/{workspace_id}/runtime-policy
GET /api/workspaces/{workspace_id}/runtime-operations
GET /api/runtime-operations/{operation_id}
GET /api/runtime-operations/{operation_id}/log
```

浏览器携带 Origin 时只允许相应 GET；PUT 继续由本机 AI/运维无浏览器请求头调用。

## 17. MCP 调用追踪

当前通用调用追踪以 `task_id` 为主。新工具调整如下：

- `apply_workspace_changes` 和 `start_workspace` 都显式接收 `task_id`，进入当前 task 的 MCP 调用链。
- `get_workspace_operation` 不接收 task_id，服务端从 operation 反查关联 task，再记录到相同调用链。
- Trace 摘要只记录文件数量、Project 数量、模式、状态和 operation ID，不记录脚本、日志或 `.env.local`。
- 现有固定工具白名单、前端筛选和 Repository 校验同步加入三个 Workspace Runtime 工具。

## 18. Migration 与兼容

新增 migration 应：

1. 创建 Workspace 运行配置、运行策略、父操作和步骤表。
2. 为活动状态、Workspace/Project 互斥和任务查询建立索引。
3. 保留 `project_runtime_files` 和 `project_runtime_runs` 原表及历史。
4. 不自动把任意 Project 配置推断成 Workspace 启动配置。
5. 允许受校验初始化脚本显式为英语 Workspace 写入 `start` 配置和策略。

旧 Project MCP 工具在兼容期读取旧记录并把新步骤投影为旧响应，不对历史数据做破坏性重写。新页面优先读取父操作模型，旧页面继续可查看历史 Project runs。

## 19. 实施阶段

### 阶段一：Workspace 编排核心

- 新表、Repository、Schema 和 migration。
- Workspace 运行配置物化。
- changed file 安全规范化、Project 路由和模式选择。
- 父操作/步骤状态聚合与互斥。
- 三个 Workspace MCP 工具及调用追踪。

### 阶段二：宿主机 Runner

- 共享 token 与 lease/heartbeat/complete API。
- Host Runner 命令、manifest 校验、进程组超时和日志。
- 手动 start/stop/status 脚本。
- 后端重启、Runner 中断和租约收敛。

### 阶段三：英语 Workspace 接入

- 注册 Workspace `start` 配置，固定调用根 `deploy-compose-full.sh`。
- 登记 Workspace 级运行文件和 Project 更新顺序。
- 在 Host Runner 下逐一预检现有六个 Project 的 fast/full `deploy.sh`，确认都只依赖注入的 `PROJECT_ROOT`、`PROJECT_HOST_ROOT`、`WORKSPACE_ROOT` 和 `WORKSPACE_HOST_ROOT`，不依赖旧后端容器的固定绝对路径。
- 更新根 `AGENTS.md`，不修改六个 Project 的通用规则。
- 配置用户级 Codex MCP 接入。
- 保留并验证根 `.env.local`。

### 阶段四：真实验收与文档

- 使用普通源码变更验证单 Project fast。
- 使用依赖文件变更验证单 Project full。
- 使用跨前后端变更验证多步骤顺序和聚合状态。
- 从英语 Workspace 任意子目录发起 `start_workspace`，验证全部服务和 CLI Runner。
- 验证失败不清理容器和数据，日志不泄漏 `.env.local`。
- 更新业务功能、启动指南、链路速查和英语 Workspace 运行文档。

## 20. 测试策略

### 20.1 单元测试

- Workspace 相对路径规范化、去重、越界和软链接逃逸。
- 最长 Project 前缀匹配与根 Project 兜底。
- fast/full/Workspace start 分类。
- 多 Project 稳定步骤顺序。
- 父状态聚合、失败后 skipped、租约过期 interrupted。
- manifest digest 和文件权限验证。
- Runner token、回环请求和无 Origin 边界。

### 20.2 Repository 与 migration 测试

- 父操作和步骤原子创建。
- Workspace/Project 活动操作互斥。
- `FOR UPDATE SKIP LOCKED` 单次领取。
- 心跳、完成、错误码和重启收敛。
- 旧 Project runtime records 保持可读。

### 20.3 MCP 协议测试

- `tools/list` 稳定包含三个新工具与兼容工具。
- 输入 Schema、annotations 和稳定错误码。
- task 与 operation 调用追踪关联。
- 多 Project 响应不返回绝对敏感路径和配置内容。

### 20.4 Host Runner 集成测试

- 使用临时 Workspace 和假 `deploy.sh` 验证领取、心跳、日志和完成。
- 篡改 manifest、入口符号链接、越界路径必须 fail-closed。
- 超时终止整个进程组。
- 两个 Runner 并发时同一操作只执行一次。
- Runner 被终止后租约过期，不自动重试。

### 20.5 真实验收

Context Router 按仓库规范通过 Docker Compose 启动和运行测试。英语 Workspace 验收使用真实 `.env.local`，但测试输出不打印其内容：

1. 手动启动 Context Router 和 Host Runner。
2. 从 `rob_english_word_back` 目录 prepare。
3. 调用 `start_workspace` 并轮询成功。
4. 验证六个容器、CLI Runner、后端健康接口和三个前端。
5. 修改一个普通业务文件，验证只创建对应 Project fast 步骤。
6. 修改一个依赖文件，验证对应 Project full。
7. 模拟失败，验证剩余步骤 skipped、容器和数据未被删除。

## 21. 验收标准

方案实现完成需要同时满足：

- 用户在注册 Workspace 任意子目录说“启动”，Codex 能通过一次 `start_workspace` 启动全部登记服务。
- Agent 不需要传 Project ID、Workspace ID、脚本路径或命令。
- 修改后一次 `apply_workspace_changes` 能正确路由一个或多个 Project。
- 完整更新判断和多 Project 顺序由 Context Router 中央维护。
- 两类操作都可通过一个 `get_workspace_operation` 查询到最终状态和有界日志。
- Host Runner 未启动时立即返回明确错误，不产生误导性 queued 操作。
- `.env.local` 只由目标部署脚本读取，不进入 MCP、数据库或日志。
- 不配置 Context Router 开机自启动；手动统一入口可以可靠启动控制面和 Host Runner。
- Runtime 失败不自动清理容器、镜像、卷或业务数据。
- 现有项目级 Runtime 配置和历史记录继续可用。

## 22. 非目标

本方案第一阶段不实现：

- Context Router 或 Host Runner 开机自启动。
- 文件系统监听和每次保存自动部署。
- 未注册目录的自动发现或执行。
- 从 MCP 传入任意 Shell 命令、环境变量或脚本正文。
- 把 `.env.local`、数据库口令或对象存储密钥迁移到 Context Router 数据库。
- Workspace 部分启动或由自然语言猜测单项目启动。
- 自动回滚、自动删除旧镜像或自动清理业务数据。
- 多 Host Runner 调度、远程 Runner、公网控制面和跨用户权限模型。
- 第一阶段并行执行多个 Project 更新。

## 23. 最终边界总结

用户提供意图，Codex 主导交互，Context Router 主导决策，Host Runner 主导受控执行，目标 Workspace 主导真实启动细节：

```text
Intent        → User
When to call  → Workspace AGENTS + MCP instructions
What to run   → Context Router registry and runtime policy
How to run    → Target Workspace materialized deploy.sh
Where to run  → Host Runtime Runner
Machine data  → Target Workspace .env.local
Truth/status  → Context Router operation records
```

该边界使统一能力集中在 Context Router，同时保留每个 Workspace 对部署脚本和本机运行配置的所有权。
