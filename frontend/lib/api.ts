import type {
  ContextTaskReadHistory,
  ContextTaskSummary,
  DatabaseEnvironment,
  DocumentDetail,
  DocumentReadStatItem,
  DocumentReadTaskItem,
  DocumentTreeNode,
  McpIntegrationInfo,
  McpIntegrationTestResult,
  McpTraceDetail,
  McpDatabaseToolPayload,
  McpTraceSummary,
  PrepareTaskContextResult,
  ProjectSummary,
  DataSourceConnectionTestResult,
  DataSourceEngineCapability,
  DataSourceDatabaseSummary,
  DataSourcePasswordReveal,
  DataSourceSummary,
  ProjectDatabaseLinkSummary,
  ProjectDataSourceOptions,
  WorkspaceDatabaseEnvironmentMappings,
  WorkspaceDataSourceSummary,
  WorkspaceEnvironmentConfig,
  WorkspaceSummary,
  WorkspaceSharedFilesResult,
  SystemGuideDetail,
  SystemGuideWrite,
} from "@/lib/types";
import {
  buildMcpTraceListPath,
  type McpTraceListQuery,
} from "@/lib/mcp-traces";
import { buildDatabasePayloadPath } from "@/lib/database-call-payload";
import { assertBrowserApiRequestAllowed } from "@/lib/browser-api-policy";

const API_URL =
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ?? "http://127.0.0.1:49173";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  assertBrowserApiRequestAllowed(path, init?.method);
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
    } | null;
    throw new Error(payload?.detail ?? `请求失败（${response.status}）`);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return request<WorkspaceSummary[]>("/api/workspaces");
}

export function listSystemGuides(): Promise<SystemGuideDetail[]> {
  return request<SystemGuideDetail[]>("/api/system-guides", { cache: "no-store" });
}

export function updateSystemGuideContent(
  guideId: string,
  document: SystemGuideWrite["document"],
): Promise<SystemGuideDetail> {
  return request<SystemGuideDetail>(`/api/system-guides/${guideId}/content`, {
    method: "PUT",
    body: JSON.stringify({ document }),
  });
}

export function reloadLocalWorkspaceMapping(): Promise<WorkspaceSummary[]> {
  return request<WorkspaceSummary[]>("/api/workspaces/reload-local-mapping", {
    method: "POST",
  });
}

export function restoreWorkspaceSharedFiles(
  workspaceId: string,
): Promise<WorkspaceSharedFilesResult> {
  return request<WorkspaceSharedFilesResult>(
    `/api/workspaces/${workspaceId}/shared-files/restore`,
    { method: "POST" },
  );
}

export function publishWorkspaceSharedFiles(
  workspaceId: string,
): Promise<WorkspaceSharedFilesResult> {
  return request<WorkspaceSharedFilesResult>(
    `/api/workspaces/${workspaceId}/shared-files/publish`,
    { method: "POST" },
  );
}

export function getWorkspace(workspaceId: string): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(`/api/workspaces/${workspaceId}`);
}

export function refreshWorkspace(
  workspaceId: string,
): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(
    `/api/workspaces/${workspaceId}/refresh`,
    { method: "POST" },
  );
}

export function listWorkspaceProjects(
  workspaceId: string,
): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>(
    `/api/workspaces/${workspaceId}/projects`,
  );
}

export function getWorkspaceDataSourceSummary(
  workspaceId: string,
): Promise<WorkspaceDataSourceSummary> {
  return request<WorkspaceDataSourceSummary>(
    `/api/workspaces/${workspaceId}/data-source-summary`,
  );
}

export function getWorkspaceDatabaseEnvironmentMappings(
  workspaceId: string,
): Promise<WorkspaceDatabaseEnvironmentMappings> {
  return request<WorkspaceDatabaseEnvironmentMappings>(
    `/api/workspaces/${workspaceId}/database-environment-mappings`,
    { cache: "no-store" },
  );
}

export function getWorkspaceEnvironmentConfig(
  workspaceId: string,
): Promise<WorkspaceEnvironmentConfig> {
  return request<WorkspaceEnvironmentConfig>(
    `/api/workspaces/${workspaceId}/environment-config`,
    { cache: "no-store" },
  );
}

export function getWorkspaceTree(
  workspaceId: string,
): Promise<DocumentTreeNode> {
  return request<DocumentTreeNode>(`/api/workspaces/${workspaceId}/tree`);
}

export function getWorkspaceDocumentDetail(
  workspaceId: string,
  documentId: string,
): Promise<DocumentDetail> {
  return request<DocumentDetail>(
    `/api/workspaces/${workspaceId}/documents/${encodeURIComponent(documentId)}`,
  );
}

export function prepareWorkspacePreview(
  workspaceId: string,
  environment?: DatabaseEnvironment,
): Promise<PrepareTaskContextResult> {
  const query = environment
    ? `?environment=${encodeURIComponent(environment)}`
    : "";
  return request<PrepareTaskContextResult>(
    `/api/workspaces/${workspaceId}/prepare-preview${query}`,
    { method: "POST" },
  );
}

export function listWorkspaceTasks(
  workspaceId: string,
): Promise<ContextTaskSummary[]> {
  return request<ContextTaskSummary[]>(
    `/api/workspaces/${workspaceId}/tasks`,
  );
}

export function getTaskDocumentReads(
  taskId: number,
): Promise<ContextTaskReadHistory> {
  return request<ContextTaskReadHistory>(
    `/api/tasks/${taskId}/document-reads`,
  );
}

export function listMcpTraces(
  query: McpTraceListQuery = {},
): Promise<McpTraceSummary[]> {
  return request<McpTraceSummary[]>(buildMcpTraceListPath(query), {
    cache: "no-store",
  });
}

export function getMcpTrace(taskId: number): Promise<McpTraceDetail> {
  return request<McpTraceDetail>(`/api/mcp-traces/${taskId}`, {
    cache: "no-store",
  });
}

export function listDocumentReadStats(params?: {
  workspace_id?: string;
  limit?: number;
}): Promise<DocumentReadStatItem[]> {
  const searchParams = new URLSearchParams();
  if (params?.workspace_id) {
    searchParams.set("workspace_id", params.workspace_id);
  }
  if (params?.limit) {
    searchParams.set("limit", params.limit.toString());
  }
  const queryStr = searchParams.toString();
  const path = `/api/document-read-stats${queryStr ? `?${queryStr}` : ""}`;
  return request<DocumentReadStatItem[]>(path, { cache: "no-store" });
}

export function getDocumentReadStatTasks(
  documentId: string,
  params?: { limit?: number },
): Promise<DocumentReadTaskItem[]> {
  const searchParams = new URLSearchParams();
  if (params?.limit) {
    searchParams.set("limit", params.limit.toString());
  }
  const queryStr = searchParams.toString();
  const encodedDocId = encodeURIComponent(documentId);
  const path = `/api/document-read-stats/${encodedDocId}/tasks${
    queryStr ? `?${queryStr}` : ""
  }`;
  return request<DocumentReadTaskItem[]>(path, { cache: "no-store" });
}

export function getMcpDatabaseToolPayload(
  taskId: number,
  toolCallId: number,
): Promise<McpDatabaseToolPayload> {
  return request<McpDatabaseToolPayload>(
    buildDatabasePayloadPath(taskId, toolCallId),
    { cache: "no-store" },
  );
}

export function getMcpIntegration(): Promise<McpIntegrationInfo> {
  return request<McpIntegrationInfo>("/api/mcp/integration");
}

export function runMcpIntegrationTest(
  workspaceId: string,
): Promise<McpIntegrationTestResult> {
  return request<McpIntegrationTestResult>("/api/mcp/integration/tests", {
    method: "POST",
    body: JSON.stringify({ workspace_id: workspaceId }),
  });
}

export function listDataSources(): Promise<DataSourceSummary[]> {
  return request<DataSourceSummary[]>("/api/data-sources");
}

export function listDataSourceEngineCapabilities(): Promise<
  DataSourceEngineCapability[]
> {
  return request<DataSourceEngineCapability[]>("/api/data-source-engines");
}

export function testDataSourceConnection(
  dataSourceId: string,
): Promise<DataSourceConnectionTestResult> {
  return request<DataSourceConnectionTestResult>(
    `/api/data-sources/${dataSourceId}/test`,
    { method: "POST" },
  );
}

export function revealDataSourcePassword(
  dataSourceId: string,
): Promise<DataSourcePasswordReveal> {
  return request<DataSourcePasswordReveal>(
    `/api/data-sources/${dataSourceId}/reveal-password`,
    { method: "POST", cache: "no-store" },
  );
}

export function listDataSourceDatabases(
  dataSourceId: string,
): Promise<DataSourceDatabaseSummary[]> {
  return request<DataSourceDatabaseSummary[]>(
    `/api/data-sources/${dataSourceId}/databases`,
  );
}

export function listDatabaseProjects(
  databaseId: string,
): Promise<ProjectDatabaseLinkSummary[]> {
  return request<ProjectDatabaseLinkSummary[]>(
    `/api/data-sources/databases/${databaseId}/projects`,
  );
}

export function getProjectDataSourceOptions(
  projectId: string,
): Promise<ProjectDataSourceOptions> {
  return request<ProjectDataSourceOptions>(
    `/api/projects/${projectId}/data-source-options`,
  );
}
