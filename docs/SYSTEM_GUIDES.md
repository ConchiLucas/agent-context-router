# 系统文档维护说明

## 目的

系统文档用于统一告诉所有接入 Context Router 的工作空间如何使用控制面能力。它属于 Context Router，不属于任何业务工作空间，因此不应写入各工作空间的 `AGENTS.md` 或 `docs/`。

系统文档以 JSONB 保存到控制面 PostgreSQL。复制整个控制面数据库时会一起复制；本机工作空间路径仍只由 `.context-router/workspaces.local.yaml` 控制。

## 状态规则

- 系统文档没有启用、停用或发布状态。
- 文档创建成功后立即进入“系统文档”菜单。
- 历史 `include_in_prepare` 字段不再改变 MCP prepare 结果。

当前 migration 内置两篇必读文档：

- `workspace-directory-access`：主目录与文档阅读目录的权限边界。
- `context-router-mcp-usage`：MCP 接入以及 prepare、文档、数据库和运行工具的标准调用顺序。

## JSON 格式

每篇文档必须是 UTF-8 JSON 对象，最大 64 KiB：

```json
{
  "schema_version": 1,
  "key": "workspace-directory-access",
  "title": "工作空间目录使用规则",
  "summary": "说明主目录与文档阅读目录的权限、同步和切换规则。",
  "sections": [
    {
      "title": "主目录",
      "rules": [
        "主目录是文档和部署文件的唯一维护目录"
      ]
    }
  ]
}
```

校验规则：

- `schema_version` 固定为 `1`。
- `key` 必须与记录的 `guide_key` 相同，只能使用小写字母、数字和单个连字符。
- `title` 为 1–120 个字符；`summary` 为 1–500 个字符。
- `sections` 必须是数组，数组内部可按具体说明需要继续使用 JSON 对象和数组。
- 不得保存密码、Token、私钥、数据库连接或某台电脑的绝对路径。

## 管理页面

左侧主菜单进入“系统文档”：

1. 左侧按当前 FastMCP `tools/list` 固定展示每个工具的独立菜单项；选择后只显示该工具的名称、中文介绍、输入/输出 Schema 和 annotations。工具项只读且不保存到 `system_guides`；中文介绍仅用于页面，AI 客户端收到的原始英文 `description` 不变。
2. 其余列表按菜单顺序展示已有文档，可同时按工具名称、描述、文档标题、摘要或 key 搜索。
3. 右侧可在“源码”和“树形”间切换；`tools/list` 两种视图均只读，系统文档源码可编辑，树形用于格式化检查。
4. 选中持久化系统文档时页面只提供“保存内容”，不能新建、删除或修改 key 和菜单顺序。
5. 保存前同时执行浏览器 JSON 解析和后端 Schema/大小校验。
6. 新文档及元数据调整由本机 AI、运维 API 或 migration 完成。

## MCP 边界

- prepare 只返回精简工作空间文档树和任务能力，不返回系统文档目录或正文。
- AI 通过 MCP `tools/list` 获取英文工具定义；页面的中文介绍只面向用户。
- 系统文档只负责页面告知，数据库和部署权限继续由后端强制校验。

## API

| 操作 | API |
| --- | --- |
| 列表 | `GET /api/system-guides` |
| 详情 | `GET /api/system-guides/{id}` |
| 浏览器保存内容 | `PUT /api/system-guides/{id}/content` |
| 本机 AI/运维完整维护 | `POST /api/system-guides`、`PUT/DELETE /api/system-guides/{id}` |

系统文档正文是浏览器唯一允许直接保存的控制面内容；后端会保留原 key 和菜单顺序。其他工作空间、项目、数据源和运行配置仍保持原有只读页面边界。
