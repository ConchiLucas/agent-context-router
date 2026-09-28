import type { JsonValue } from "@/lib/types";

export const LIVE_MCP_TOOL_NAMES = [
  "prepare_task_context",
  "read_task_context",
  "read_middleware_context",
  "search_context_documents",
  "read_context_document",
  "resolve_database_target",
  "search_database_objects",
  "execute_database_query",
  "save_data_visualization_query",
  "save_task_visualization_result",
  "list_task_containers",
  "inspect_container_errors",
  "read_table_relations",
  "search_relation_tables",
  "search_value_mappings",
  "resolve_value_candidates",
  "execute_mapped_data_query",
  "search_forwarding_interfaces",
  "compare_forwarding_interfaces",
  "read_forwarding_interface_detail",
  "read_forwarding_request_history",
  "prepare_forwarding_request",
  "execute_forwarding_request",
  "apply_workspace_changes",
  "start_workspace",
  "get_workspace_operation",
] as const;

export type LiveMcpToolName = (typeof LIVE_MCP_TOOL_NAMES)[number];

export interface McpToolGroupSpec {
  id: string;
  label: string;
  tools: readonly LiveMcpToolName[];
}

export const MCP_TOOL_GROUPS: readonly McpToolGroupSpec[] = [
  {
    id: "context",
    label: "任务与上下文",
    tools: ["prepare_task_context", "read_task_context", "read_middleware_context"],
  },
  {
    id: "documents",
    label: "文档",
    tools: ["search_context_documents", "read_context_document"],
  },
  {
    id: "database",
    label: "数据库",
    tools: ["resolve_database_target", "search_database_objects", "execute_database_query"],
  },
  {
    id: "table-relations",
    label: "表关联",
    tools: ["read_table_relations", "search_relation_tables"],
  },
  {
    id: "value-mappings",
    label: "取值映射",
    tools: ["search_value_mappings", "resolve_value_candidates"],
  },
  {
    id: "interfaces",
    label: "接口转发",
    tools: [
      "search_forwarding_interfaces",
      "compare_forwarding_interfaces",
      "read_forwarding_interface_detail",
      "read_forwarding_request_history",
      "prepare_forwarding_request",
      "execute_forwarding_request",
    ],
  },
  {
    id: "visualization",
    label: "可视化",
    tools: [
      "save_data_visualization_query",
      "execute_mapped_data_query",
      "save_task_visualization_result",
      "list_task_containers",
      "inspect_container_errors",
    ],
  },
  {
    id: "runtime",
    label: "工作空间运行",
    tools: ["apply_workspace_changes", "start_workspace", "get_workspace_operation"],
  },
];

export const MCP_TOOL_DESCRIPTIONS_ZH: Readonly<Record<LiveMcpToolName, string>> = {
  prepare_task_context:
    "根据当前工作目录识别 Workspace，创建 task_id，并返回精简文档树和可用能力。",
  read_task_context:
    "按需读取当前任务的数据库别名或环境配置，不在 prepare 阶段默认返回。",
  read_middleware_context:
    "按当前任务环境读取 Redis、MQ、Elasticsearch、MinIO、任务调度等中间件的实时权威信息。",
  search_context_documents:
    "在当前 Workspace 的项目文档中搜索相关内容，返回匹配文档和章节定位，不返回正文。",
  read_context_document:
    "按文档 ID 读取完整 Markdown、指定章节或系统文档，一次可以批量读取多个目标。",
  resolve_database_target:
    "按映射、表名或业务提示解析当前任务可用的数据库别名和目标，不执行查询。",
  search_database_objects:
    "在当前任务已授权的数据库中搜索 Schema、表、视图、字段或索引。",
  execute_database_query:
    "使用 read_task_context 返回的数据库别名执行一条受限制的只读 SQL。",
  save_data_visualization_query:
    "把当前任务识别出的关联数据查询条件保存到数据可视化页面，等待人工确认执行。",
  save_task_visualization_result:
    "把当前任务的脱敏结论、代码位置、后续建议和验证结果保存到任务可视化页面。",
  list_task_containers:
    "列出当前任务 Workspace 通过运行标签注册的 Docker 容器，不返回其他容器。",
  inspect_container_errors:
    "读取一个已注册容器的有界日志快照，确认错误后脱敏并写入日志可视化。",
  read_table_relations:
    "读取当前 Workspace 已发布的表关联、写入入口和更新入口。",
  search_relation_tables:
    "按业务词或表名搜索当前 Workspace 已发布的表关联目录。",
  search_value_mappings:
    "按业务关键词或接口参数查找当前 Workspace 已发布的取值映射。",
  resolve_value_candidates:
    "使用已配置的只读数据库规则解析业务值候选，省略环境时继承任务环境。",
  execute_mapped_data_query:
    "按已发布取值映射执行受限制的只读查询，并把结果写入数据可视化。",
  search_forwarding_interfaces:
    "在当前任务环境中搜索已导入接口，并显示是否具备可调用路由。",
  compare_forwarding_interfaces:
    "对比 2 到 5 个候选接口的路径、方法和出入参差异，便于选定最终调用目标。",
  read_forwarding_interface_detail:
    "读取单个已导入接口的完整定义、路由和取值绑定，不发送业务请求。",
  read_forwarding_request_history:
    "读取当前任务环境内单个接口最近的请求记录，按需返回有界响应，不返回账号请求头。",
  prepare_forwarding_request:
    "默认复用成功日志；按取值策略定向刷新或重建业务值，并生成短期只读执行计划。",
  execute_forwarding_request:
    "校验计划摘要后单次执行只读接口，请求头由服务端安全注入。",
  apply_workspace_changes:
    "根据 Workspace 相对变更路径定位受影响项目，并选择快速或完整更新。",
  start_workspace:
    "使用 Workspace 的统一启动配置，启动其中所有已登记的项目和服务。",
  get_workspace_operation:
    "查询 Workspace 启动或更新操作的状态、执行步骤和有界日志。",
};

const TOOL_GROUP_BY_NAME = new Map<string, McpToolGroupSpec>(
  MCP_TOOL_GROUPS.flatMap((group) => group.tools.map((name) => [name, group])),
);

export function mcpToolName(tool: Record<string, JsonValue>): string | null {
  return typeof tool.name === "string" ? tool.name : null;
}

export function displayMcpToolDescription(tool: Record<string, JsonValue>): string {
  const name = mcpToolName(tool);
  if (name && name in MCP_TOOL_DESCRIPTIONS_ZH) {
    return MCP_TOOL_DESCRIPTIONS_ZH[name as LiveMcpToolName];
  }
  return typeof tool.description === "string" ? tool.description : "当前 MCP 工具定义";
}

export function groupMatchesQuery(label: string, query: string): boolean {
  return label.toLocaleLowerCase("zh-CN").includes(query);
}

export interface GroupedMcpTools<T> {
  id: string;
  label: string;
  tools: T[];
}

export function groupMcpTools<T>(
  tools: T[],
  nameOf: (tool: T) => string | null,
): GroupedMcpTools<T>[] {
  const toolsByName = new Map<string, T>();
  const other: T[] = [];
  for (const tool of tools) {
    const name = nameOf(tool);
    if (!name) continue;
    if (TOOL_GROUP_BY_NAME.has(name)) {
      toolsByName.set(name, tool);
    } else {
      other.push(tool);
    }
  }
  const grouped: GroupedMcpTools<T>[] = MCP_TOOL_GROUPS.flatMap((group) => {
    const items = group.tools.flatMap((name) => {
      const item = toolsByName.get(name);
      return item ? [item] : [];
    });
    return items.length > 0 ? [{ id: group.id, label: group.label, tools: items }] : [];
  });
  if (other.length > 0) {
    grouped.push({ id: "other", label: "其他", tools: other });
  }
  return grouped;
}
