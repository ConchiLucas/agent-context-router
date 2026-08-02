# 英语 Workspace 六项目增量修复与验收设计

## 目标

修复英语 Workspace 三个前端 Project 的非法 fast Compose 配置，防止 Context Router 再次保存语法错误的 YAML；优化目标根 `AGENTS.md` 的运行编排规则，并证明六个登记 Project 都能完成真实 fast 增量更新。验收结束后回滚临时源码改动，并对回滚结果再次执行增量更新。

## 根因

Context Router PostgreSQL 中保存的三个前端 `fast/compose.yml` 在 YAML literal block `|-` 下缺少内容缩进。当前 Project 运行配置 API 只校验文件路径与重复项，不校验 `.yml/.yaml` 语法，因此错误直到 Host Runner 调用 Docker Compose 时才暴露。

修正 YAML 后的首个 Go 真实增量又暴露出第二个边界问题：六份旧 fast 脚本各自引用 Project `.env` 或工作空间 `.runtime-runner-secrets/{project_id}.env`，绕开了已经约定的根 `.env.local` 唯一机器差异入口。这不是单台电脑缺文件，而是运行配置仍复制了旧部署体系。

受影响 Project：

- `word_select_dashboard/web-react`
- `rob_english_word_front`
- `rob_english_word_cloze_web`

## 修复设计

1. 在 `RuntimeConfigModeUpdate` 保存边界对所有 `.yml`、`.yaml` 文件执行 PyYAML `safe_load` 语法校验。空文件允许；解析失败返回 Pydantic 422，不写数据库。应用级 `RequestValidationError` 处理器统一移除 Pydantic 默认的 `input` 和 `ctx`，避免 YAML 或其他管理请求的完整输入进入错误响应；自定义消息只保留文件、行和列。这里仍只做 YAML 语法校验，不把 Docker Compose 语义耦合进 Schema。
2. 通过受校验 Project Runtime Config API 修正三个前端 fast 配置的 literal block 缩进，确认六份 YAML 都能通过新的保存校验。
3. 在目标根 `deploy-compose-full.sh` 增加 `--project <key>`：仍加载并校验根 `.env.local`、预检六份 Compose 和公共依赖，但只执行所选 Project 的既有启动函数与容器检查。无参数保持原有全量启动及 CLI Runner 行为。
4. 将六个 Project 的 fast 配置统一替换为只含 `deploy.sh` 的无凭据包装器，调用 `"$WORKSPACE_HOST_ROOT/deploy-compose-full.sh" --project <key>`。数据库只保存调度信息，不保存或复制任何机器凭据。
5. 优化英语 Workspace 根 `AGENTS.md`：
   - `get_workspace_operation` 明确只传返回的 `operation_id`，由服务端从操作记录解析任务归属；
   - 修改完成后一次提交本轮全部真实 Workspace 相对路径；
   - 单项目改动预期只产生一个 fast 步骤；
   - 启动仍统一使用 `start_workspace` 启动全部项目；
   - 操作失败只报告，不自动修复或清理，除非用户明确要求。

## 六项目验收

为每个 Project 选择一个已跟踪、能进入其构建或开发运行链路的源码入口，只加入唯一的无业务影响注释：

| Project | 验收文件 |
| --- | --- |
| Go 管理服务 | `word_select_dashboard/server/main.go` |
| Python Agent | `word_select_dashboard/word-agent/src/word_agent/main.py` |
| Java 核心后端 | `rob_english_word_back/src/main/java/com/robword/RobEnglishWordApplication.java` |
| React 管理端 | `word_select_dashboard/web-react/src/App.tsx` |
| Vue 主前端 | `rob_english_word_front/src/router/index.ts` |
| React 完形前端 | `rob_english_word_cloze_web/src/App.tsx` |

每个 Project 单独创建一次 `apply_workspace_changes` 操作并轮询终态，要求：

- 只路由到对应 Project；
- 选择 `fast`；
- Host Runner 实际执行 `deploy.sh`；
- 操作终态为 `succeeded`、退出码为 0；
- 对应容器仍在运行。

首轮六项全部成功后，用 `apply_patch` 精确删除六处测试注释。随后对同一批六个回滚路径再次逐项目执行增量更新，并要求同样全部成功。这既恢复磁盘源码，也让运行态重新消费恢复后的代码。

## 安全与失败边界

- 不读取、输出、提交或物化目标 `.env.local`。
- API 级失败测试使用虚构敏感标记验证 422 不回显输入，并验证非法请求不会覆盖旧运行配置。
- Project fast 快照不再包含 `.env`、`runtime.env` 或 `.runtime-runner-secrets` 路径；所有机器差异只由根脚本读取 `.env.local`。
- 不修改业务数据，不删除容器、镜像、Volume 或数据库。
- 任一增量失败时停止该轮后续判断，保留现场和日志，先定位原因；不把失败掩盖为成功。
- 回滚只删除本次写入的唯一测试注释，不覆盖用户已有改动。
- 永久提交只包含 Context Router 校验/测试/文档、目标 `AGENTS.md` 和必要运行配置更新；六处临时测试注释不得进入提交。

## 自动验证

- 后端 Schema/API 回归测试先红后绿。
- Context Router 后端全量 pytest、Ruff check、Ruff format check。
- 前端 lint、test、build（若本轮未改前端，仍作为完整回归）。
- migration head 检查。
- 两个仓库 `git diff --check` 和干净边界检查。
