# 功能开发记录

本文件记录新功能或已有功能改造的代码层面内容。

## 记录规则

- 只记录会影响后续开发、维护或排查的功能实现信息。
- 普通交流、临时想法和未落地内容不记录。

## 记录

### 2026-07-27：项目文档集中到 Workspace docs

- 项目配置拆分为“源码相对路径”和“文档入口相对路径”。源码目录不再强制包含 `AGENTS.md`，新入口统一配置在 Workspace 的 `docs/{frontend|backend}/{项目}/AGENTS.md`。
- 新增/编辑表单和项目卡片分别展示两类路径；文档入口默认根据项目类型和源码末级目录生成建议，用户手工修改后不再覆盖。
- cwd 和 `active_project` 只按源码根匹配；查看文档树、Workspace 搜索、read 和 MCP JSON 按独立文档入口构建。
- Workspace 刷新会一次检查并展示全部坏入口，同时保留上一版完整映射。刷新失败后前端仍重新读取项目列表和工作空间摘要。
- migration head 更新为 `20260727_0016`，旧记录先保持原入口位置，具体工作空间可分批搬迁到 docs。

### 2026-07-26：工作空间管理

- 工作空间作为顶层目录卡片，可独立维护名称、类型、绝对根目录和启停状态；进入工作空间后再配置根项目 `.` 或嵌套项目相对路径。
- Project 只保留名称、`frontend/backend` 类型、相对路径和各自的数据源授权，没有独立 enabled。授权修改仍从具体项目卡片的“管理数据源”进入。
- Codex task、prepare/search/read、调用记录、文档树、刷新和 MCP JSON 均以 Workspace 为边界；cwd 匹配最深 Workspace，最深 Project 只作为 `active_project` 元数据。
- Workspace task 可以使用全部子项目当前有效的数据库授权，`mcp_alias` 在 Workspace 内大小写无关唯一；数据源汇总只聚合展示，不复制授权或策略。
- 工作空间详情使用“前端项目 / 后端项目 / 数据源汇总”三页签，Workspace 工具栏承载上下文操作，项目卡片只保留“编辑项目 / 管理数据源 / 删除项目”。
- Workspace 根目录存在 `AGENTS.md` 时自动作为工作空间级文档入口并进入 prepare/search/read；不存在时保持合成根。该入口与 Project 文档分别建立派生索引，重复文档只在聚合结果中保留一次。
- migration head 为 `20260726_0015`。升级前项目会保留为根项目；旧 task 保持 `scope='project'` 兼容，新 task 使用 `scope='workspace'`，旧项目 ID、数据库授权和历史链路不变。
