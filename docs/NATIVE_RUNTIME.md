# Context Router Native 运行架构

## 边界

Context Router 的 Backend、Frontend 和 Host Runner 运行在宿主机。已注册 Workspace 继续使用各自的 Docker Compose；Context Router 停止时不得停止这些业务容器。

```text
Native Backend / Frontend
  -> PostgreSQL、文档和源码
  -> Docker Unix Socket（只读状态、日志及既有受限容器动作）
  -> Host Runner 短租约
  -> Workspace 固定 deploy.sh
  -> Workspace Docker Compose
```

## 本机配置

从 `.env.native.example` 复制 `.env.native.local`。该文件被 Git 忽略。必须设置真实的数据库 URL、Workspace 根、映射文件、共享配置中心地址、Runtime Root 和 Docker Socket。

Frontend 运行时固定为 Node.js 22。Native 脚本会依次使用 `CONTEXT_ROUTER_NODE_HOME`、Apple Silicon Homebrew、Intel Homebrew 和当前 `PATH` 中满足版本要求的 Node；找不到时直接失败并给出安装提示，不再用其他主版本继续启动。

Host Runner 由 `launchd` 托管时不会继承交互式 Shell 的完整 `PATH`。Native 脚本会补齐 Docker Desktop、Homebrew 和系统命令目录，并在 macOS 上自动识别 IntelliJ IDEA 内置 Maven。其他工作空间工具链目录可通过 `CONTEXT_ROUTER_HOST_TOOL_PATHS` 配置，多个目录使用冒号分隔。

`CONTEXT_ROUTER_WORKSPACE_ROOT` 是文档、源码定位和 cwd 路由的允许根。`CONTEXT_ROUTER_RUNTIME_ROOT` 保存快照、日志、PID 和 Runner Token。两个目录不能通过不受控软链接扩大访问范围。

## 生命周期

- `scripts/bootstrap-native.sh`：检查工具链并安装锁定依赖。
- `scripts/dev-native.sh`：以前台开发模式启动三项服务。
- `scripts/start-native-stack.sh`：migration、Backend、Runner、Frontend 生产构建与启动；macOS 下使用当前登录会话的 `launchd` 托管进程，但不安装开机启动项。
- `scripts/status-native-stack.sh`：检查 PID、HTTP、Runner 心跳和 Docker Engine。
- `scripts/stop-native-stack.sh`：只停止 Context Router，不停止 Workspace 容器。
- `scripts/restart-native-stack.sh`：重启 Context Router Native Stack。

## 验证

```bash
cd backend
UV_PROJECT_ENVIRONMENT=.venv-native uv run --extra dev pytest -q
UV_PROJECT_ENVIRONMENT=.venv-native uv run --extra dev ruff check .
UV_PROJECT_ENVIRONMENT=.venv-native uv run --extra dev ruff format --check .
uv run alembic current

cd ../frontend
npm test
npm run lint
npm run build
```

ClickHouse 集成测试仍可单独启动 Docker 测试依赖；这不代表 Context Router 自身由 Docker 启动。

迁移观察期内根 `docker-compose.yml` 和 `.env.container.example` 只作为回滚入口。Native 链路验收稳定后，可以把 ClickHouse 测试服务拆到独立 Compose 文件，再删除 Context Router Backend/Frontend 的容器定义；不得删除已注册 Workspace 自己的 Compose 文件。

## 安全约束

- Backend 和 Frontend 只监听 `127.0.0.1`。
- Docker Endpoint 只接受本地 Unix Socket。
- 新运行操作只能通过 Host Runner，Backend 的旧直接执行能力保持关闭。
- Runner Token 权限为 `0600`，Runtime Root 权限为 `0700`。
- 只能读取带当前 Workspace 稳定标签的容器日志。
- 数据库密码、Nacos 密钥、接口账号 Header 和 Runner Token不得进入日志或提交。
