import type {
  McpTraceDocumentArtifactItem,
  McpTraceSummary,
  McpTraceToolCall,
} from "@/lib/types";

export interface McpTraceFilters {
  query: string;
  agentName: string;
  serverName: string;
  status: "all" | "ok" | "error";
}

export interface McpTraceListQuery {
  projectId?: string;
  agentName?: string;
  serverName?: string;
  toolName?: string;
  status?: "running" | "ok" | "error" | "cancelled";
  keyword?: string;
  limit?: number;
}

export interface McpTraceGraphRow {
  call: McpTraceToolCall;
  depth: number;
  parentSequence: number | null;
}

function normalized(value: string): string {
  return value.trim().toLocaleLowerCase();
}

export function buildMcpTraceListPath(query: McpTraceListQuery = {}): string {
  const search = new URLSearchParams();
  if (query.projectId) search.set("project_id", query.projectId);
  if (query.agentName) search.set("agent_name", query.agentName);
  if (query.serverName) search.set("server_name", query.serverName);
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
  const query = normalized(filters.query);

  return traces.filter((trace) => {
    if (
      filters.agentName &&
      (trace.agent_name ?? "") !== filters.agentName
    ) {
      return false;
    }
    if (
      filters.serverName &&
      !trace.server_names.includes(filters.serverName)
    ) {
      return false;
    }
    if (filters.status === "error" && trace.error_count === 0) return false;
    if (
      filters.status === "ok" &&
      (trace.error_count > 0 || trace.call_count === 0)
    ) {
      return false;
    }
    if (!query) return true;

    return [
      String(trace.task_id),
      trace.task,
      trace.project_name,
      trace.cwd,
      trace.agent_name ?? "",
      trace.server_names.join(" "),
    ].some((value) => normalized(value).includes(query));
  });
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
