# 系统文档维护说明

## 目的

系统文档用于统一告诉所有接入 Context Router 的工作空间如何使用控制面能力。它属于 Context Router，不属于任何业务工作空间，因此不应写入各工作空间的 `AGENTS.md` 或 `docs/`。

系统文档以 JSONB 保存到控制面 PostgreSQL。复制整个控制面数据库时会一起复制；本机工作空间路径仍只由 `.context-router/workspaces.local.yaml` 控制。

## 状态规则

- 系统文档没有启用、停用或发布状态。
- 文档创建成功后立即进入“系统文档”菜单和后续 prepare 的 `catalog`。
- `include_in_prepare` 只控制 prepare 是否直接携带完整 JSON，不影响文档是否存在或能否读取。

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

1. 左侧列表按菜单顺序展示已有文档，可按标题、摘要或 key 搜索。
2. 右侧可在“源码”和“树形”间切换；源码用于编辑，树形用于格式化检查。
3. 页面只提供“保存内容”，不能新建、删除或修改 key、菜单顺序和 prepare 返回策略。
4. 保存前同时执行浏览器 JSON 解析和后端 Schema/大小校验。
5. 新文档及元数据调整由本机 AI、运维 API 或 migration 完成。

## prepare 和读取

prepare 增加两个稳定字段：

```json
{
  "workspace_access": {
    "mode": "documents_only",
    "message": "当前目录是文档阅读目录，可以读取主目录共享文档；不能使用数据库、部署或共享文件覆盖功能。"
  },
  "system_guides": {
    "required": [],
    "catalog": [
      {
        "document_id": "system-guide:workspace-directory-access",
        "key": "workspace-directory-access",
        "title": "工作空间目录使用规则",
        "summary": "说明主目录与文档阅读目录的权限、同步和切换规则。"
      }
    ]
  }
}
```

- `workspace_access` 是本机映射服务动态计算的当前权限，不能由系统文档覆盖。
- `required` 包含标记为 prepare 直接返回全文的文档。
- `catalog` 始终包含全部系统文档的 ID、标题和摘要。
- `system-guide:*` ID 可直接传给现有 `read_context_document`；系统 JSON 文档不支持 Markdown `section` 参数。
- 系统文档只负责告知，数据库和部署权限继续由后端强制校验。

## API

| 操作 | API |
| --- | --- |
| 列表 | `GET /api/system-guides` |
| 详情 | `GET /api/system-guides/{id}` |
| 浏览器保存内容 | `PUT /api/system-guides/{id}/content` |
| 本机 AI/运维完整维护 | `POST /api/system-guides`、`PUT/DELETE /api/system-guides/{id}` |

系统文档正文是浏览器唯一允许直接保存的控制面内容；后端会保留原 key、菜单顺序和 prepare 策略。其他工作空间、项目、数据源和运行配置仍保持原有只读页面边界。
