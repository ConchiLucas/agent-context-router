# AGENTS.md 文档树

这是一个以绝对路径 `AGENTS.md` 为项目入口的递归文档索引。后端读取固定格式的“下级文档”表格，把树结构和每个 Markdown 文件的完整内容放入内存；前端用项目卡片、全屏树和详情面板展示。

## 文档约定

根入口必须命名为 `AGENTS.md`。需要下级文档时增加：

```markdown
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 后端架构、接口和服务说明 | `./docs/backend/backend.md` |
```

- 只有 `## 下级文档` 下的两列表格参与树映射。
- 相对路径以当前 Markdown 文件所在目录为基准。
- 路径必须以 `./` 开头、指向 `.md` 文件，并且不能越出当前目录。
- 下级文档可以继续声明自己的下级，目录深度不受限制。
- 正文中的普通 Markdown 链接不参与父子层级。

## 运行方式

项目只通过当前目录的 Docker Compose 管理：

```bash
docker compose up -d --force-recreate backend frontend
```

- Web：<http://127.0.0.1:49174>
- API：<http://127.0.0.1:49173>
- API 文档：<http://127.0.0.1:49173/docs>

Compose 默认把 `/Users/conchi/workforce` 只读挂载到后端 `/workspace`，并预置攀枝花多式联运示例。其他机器或服务器通过 `.env` 覆盖：

```text
CONTEXT_ROUTER_WORKSPACE_HOST_ROOT=/absolute/workspace/root
CONTEXT_ROUTER_DEFAULT_PROJECT_NAME=示例项目
CONTEXT_ROUTER_DEFAULT_AGENTS_PATH=/absolute/workspace/root/project/AGENTS.md
```

页面也可以临时添加多个项目。当前版本的项目配置、文档树和 Markdown 内容都保存在后端进程内；后端重启后，页面临时添加的项目会清空，环境变量配置的默认项目会重新加载。

## 刷新行为

点击“刷新映射”时，后端从根 `AGENTS.md` 重新递归读取所有下级文档，在全新的临时缓存中构建整棵树，完成后一次性替换旧缓存。因此成功刷新后不会残留已删除节点或旧文件内容；刷新失败则保留上一份完整缓存。

## 核心 API

| API | 作用 |
| --- | --- |
| `GET /api/projects` | 获取项目卡片 |
| `POST /api/projects` | 添加项目并首次映射 |
| `POST /api/projects/{id}/refresh` | 全量重建该项目内存缓存 |
| `GET /api/projects/{id}/tree` | 获取不含正文的递归树 |
| `GET /api/projects/{id}/documents/{document_id}` | 从内存获取 Markdown 正文 |

开发、测试和重启命令见 [启动与开发规范](./docs/STARTUP_GUIDE.md)。

