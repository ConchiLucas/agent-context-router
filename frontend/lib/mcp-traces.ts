import type {
  InternalMcpTraceToolCall,
  InternalMcpToolName,
  McpTraceCompleteness,
  McpTraceDocumentArtifactItem,
  McpTraceSummary,
  McpTraceToolCall,
} from "@/lib/types";

export const INTERNAL_MCP_TOOL_NAMES: readonly InternalMcpToolName[] = [
  "prepare_task_context",
  "read_task_context",
  "read_middleware_context",
  "search_context_documents",
  "read_context_document",
  "search_database_objects",
  "execute_database_query",
  "list_task_containers",
  "inspect_container_errors",
  "read_table_relations",
  "search_relation_tables",
  "search_value_mappings",
  "resolve_value_candidates",
  "search_forwarding_interfaces",
  "read_forwarding_request_history",
  "prepare_forwarding_request",
  "execute_forwarding_request",
  "apply_workspace_changes",
  "start_workspace",
  "get_workspace_operation",
  "apply_project_changes",
  "get_project_operation",
  "prepare_table_relation_context",
];

export type McpTraceStatusFilter = "all" | "running" | "ok" | "error";

const TRACE_WARNING_MESSAGES: Readonly<Record<string, string>> = {
  running_calls: "仍有内部工具调用正在运行，链路内容会继续更新。",
  legacy_calls: "包含升级前的历史记录，部分调用细节可能缺失。",
  unlinked_document_reads: "部分文档读取记录无法关联到对应工具调用。",
  unlinked_database_calls: "部分数据库访问记录无法关联到对应工具调用。",
  interrupted_calls: "部分调用在服务重启前未正常结束。",
  no_trace_calls: "这个任务没有可展示的内部工具调用记录。",
  missing_prepare_call:
    "缺少 prepare_task_context 调用记录，任务起点可能未完整落库。",
};

const UNKNOWN_TRACE_WARNING = "链路包含无法完整还原的记录。";

export interface McpTraceFilters {
  status: McpTraceStatusFilter;
}

export interface McpTraceListQuery {
  projectId?: string;
  agentName?: string;
  toolName?: InternalMcpToolName;
  status?: "running" | "ok" | "error" | "cancelled";
  keyword?: string;
  limit?: number;
}

export interface McpTraceGraphRow {
  call: McpTraceToolCall;
  depth: number;
  parentSequence: number | null;
}

export function buildMcpTraceListPath(query: McpTraceListQuery = {}): string {
  const search = new URLSearchParams();
  if (query.projectId) search.set("project_id", query.projectId);
  if (query.agentName) search.set("agent_name", query.agentName);
  if (query.toolName) search.set("tool_name", query.toolName);
  if (query.status) search.set("status", query.status);
  if (query.keyword) search.set("keyword", query.keyword);
  if (query.limit !== undefined) {
    search.set("limit", String(Math.min(Math.max(query.limit, 1), 100)));
  }
  const suffix = search.toString();
  return `/api/mcp-traces${suffix ? `?${suffix}` : ""}`;
}

export function sortTraceCalls(
  calls: McpTraceToolCall[],
): McpTraceToolCall[] {
  return [...calls].sort(
    (left, right) =>
      left.sequence - right.sequence ||
      left.tool_call_id - right.tool_call_id,
  );
}

export function filterMcpTraces(
  traces: McpTraceSummary[],
  filters: McpTraceFilters,
): McpTraceSummary[] {
  return traces.filter((trace) => {
    if (filters.status === "error" && trace.error_count === 0) return false;
    if (
      filters.status === "ok" &&
      (trace.error_count > 0 || trace.call_count === 0)
    ) {
      return false;
    }
    return true;
  });
}

export function statusQueryForTraceFilter(
  status: McpTraceStatusFilter,
): "running" | "error" | undefined {
  if (status === "running" || status === "error") return status;
  return undefined;
}

export function isInternalMcpToolName(
  value: string,
): value is InternalMcpToolName {
  return (INTERNAL_MCP_TOOL_NAMES as readonly string[]).includes(value);
}

export function internalTraceCalls(
  calls: McpTraceToolCall[],
): InternalMcpTraceToolCall[] {
  return calls.filter((call): call is InternalMcpTraceToolCall => {
    return (
      isInternalMcpToolName(call.tool_name) &&
      (call.source === "server" || call.source === "legacy")
    );
  });
}

export function traceCompletenessLabel(
  status: McpTraceCompleteness,
): "完整" | "运行中" | "可能不完整" {
  if (status === "running") return "运行中";
  if (status === "partial") return "可能不完整";
  return "完整";
}

export function traceWarningMessages(warnings: string[]): string[] {
  const messages = warnings.map(
    (warning) => TRACE_WARNING_MESSAGES[warning] ?? UNKNOWN_TRACE_WARNING,
  );
  return Array.from(new Set(messages));
}

function documentItems(
  call: McpTraceToolCall,
): McpTraceDocumentArtifactItem[] {
  return call.artifacts.flatMap((artifact) => {
    if (
      artifact.kind !== "document_read" ||
      !("documents" in artifact) ||
      !Array.isArray(artifact.documents)
    ) {
      return [];
    }
    return artifact.documents as McpTraceDocumentArtifactItem[];
  });
}

export function documentsForTraceCall(
  call: McpTraceToolCall,
): McpTraceDocumentArtifactItem[] {
  return documentItems(call).sort(
    (left, right) => left.position - right.position,
  );
}

export function traceCallResultSummary(
  call: McpTraceToolCall,
): string | null {
  if (call.tool_name !== "search_context_documents") return null;
  const returnedCount = call.result_summary?.returned_count;
  if (
    typeof returnedCount !== "number" ||
    !Number.isInteger(returnedCount) ||
    returnedCount < 0
  ) {
    return null;
  }
  return `返回 ${returnedCount} 个文档`;
}

export function buildTraceDocumentCallNumbers(
  calls: McpTraceToolCall[],
): ReadonlyMap<string, number[]> {
  const callNumbers = new Map<string, number[]>();

  sortTraceCalls(calls).forEach((call) => {
    const documentIds = new Set(
      documentsForTraceCall(call)
        .filter((document) => document.status === "ok")
        .map((document) => document.document_id),
    );

    documentIds.forEach((documentId) => {
      callNumbers.set(documentId, [
        ...(callNumbers.get(documentId) ?? []),
        call.sequence,
      ]);
    });
  });

  return callNumbers;
}

export function buildTraceGraphRows(
  calls: McpTraceToolCall[],
): McpTraceGraphRow[] {
  const sortedCalls = sortTraceCalls(calls);
  const callsById = new Map(
    sortedCalls.map((call) => [call.tool_call_id, call]),
  );
  const depthById = new Map<number, number>();

  function depthOf(call: McpTraceToolCall, trail: Set<number>): number {
    const cached = depthById.get(call.tool_call_id);
    if (cached !== undefined) return cached;

    const parentId = call.parent_tool_call_id;
    if (!parentId || trail.has(call.tool_call_id)) {
      depthById.set(call.tool_call_id, 0);
      return 0;
    }

    const parent = callsById.get(parentId);
    if (!parent) {
      depthById.set(call.tool_call_id, 0);
      return 0;
    }

    const nextTrail = new Set(trail);
    nextTrail.add(call.tool_call_id);
    const depth = Math.min(depthOf(parent, nextTrail) + 1, 8);
    depthById.set(call.tool_call_id, depth);
    return depth;
  }

  return sortedCalls.map((call) => {
    const parent = call.parent_tool_call_id
      ? callsById.get(call.parent_tool_call_id)
      : undefined;
    return {
      call,
      depth: depthOf(call, new Set()),
      parentSequence: parent?.sequence ?? null,
    };
  });
}
