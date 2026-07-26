import type {
  ContextTaskReadHistory,
  ContextTaskSummary,
  DocumentDetail,
  DocumentTreeNode,
  McpIntegrationInfo,
  McpIntegrationTestResult,
  McpTraceDetail,
  McpDatabaseToolPayload,
  McpTraceSummary,
  PrepareTaskContextResult,
  ProjectSummary,
  DataSourceDatabasePayload,
  DataSourceConnectionTestResult,
  DataSourceEngineCapability,
  DataSourceDatabaseSyncResult,
  DataSourceDatabaseSummary,
  DataSourcePasswordReveal,
  DataSourcePayload,
  DataSourceSummary,
  ProjectDatabaseLinkPayload,
  ProjectDatabaseLinkSummary,
  ProjectDataSourceOptions,
  WorkspaceCreate,
  WorkspaceDataSourceSummary,
  WorkspaceProjectCreate,
  WorkspaceProjectUpdate,
  WorkspaceSummary,
  WorkspaceUpdate,
} from "@/lib/types";
import {
  buildMcpTraceListPath,
  type McpTraceListQuery,
} from "@/lib/mcp-traces";
import { buildDatabasePayloadPath } from "@/lib/database-call-payload";

const API_URL =
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ?? "http://127.0.0.1:49173";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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

export function getWorkspace(workspaceId: string): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(`/api/workspaces/${workspaceId}`);
}

export function createWorkspace(
  payload: WorkspaceCreate,
): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>("/api/workspaces", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateWorkspace(
  workspaceId: string,
  payload: WorkspaceUpdate,
): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(`/api/workspaces/${workspaceId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function setWorkspaceEnabled(
  workspaceId: string,
  enabled: boolean,
): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(`/api/workspaces/${workspaceId}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  await request<unknown>(`/api/workspaces/${workspaceId}`, {
    method: "DELETE",
  });
}

export function listWorkspaceProjects(
  workspaceId: string,
): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>(
    `/api/workspaces/${workspaceId}/projects`,
  );
}

export function createWorkspaceProject(
  workspaceId: string,
  payload: WorkspaceProjectCreate,
): Promise<ProjectSummary> {
  return request<ProjectSummary>(
    `/api/workspaces/${workspaceId}/projects`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

export function updateWorkspaceProject(
  workspaceId: string,
  projectId: string,
  payload: WorkspaceProjectUpdate,
): Promise<ProjectSummary> {
  return request<ProjectSummary>(
    `/api/workspaces/${workspaceId}/projects/${projectId}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteWorkspaceProject(
  workspaceId: string,
  projectId: string,
): Promise<void> {
  await request<unknown>(
    `/api/workspaces/${workspaceId}/projects/${projectId}`,
    { method: "DELETE" },
  );
}

export function getWorkspaceDataSourceSummary(
  workspaceId: string,
): Promise<WorkspaceDataSourceSummary> {
  return request<WorkspaceDataSourceSummary>(
    `/api/workspaces/${workspaceId}/data-source-summary`,
  );
}

export function refreshWorkspaceMapping(
  workspaceId: string,
): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(`/api/workspaces/${workspaceId}/refresh`, {
    method: "POST",
  });
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
): Promise<PrepareTaskContextResult> {
  return request<PrepareTaskContextResult>(
    `/api/workspaces/${workspaceId}/prepare-preview`,
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

export function createDataSource(
  payload: DataSourcePayload,
): Promise<DataSourceSummary> {
  return request<DataSourceSummary>("/api/data-sources", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateDataSource(
  dataSourceId: string,
  payload: DataSourcePayload,
): Promise<DataSourceSummary> {
  return request<DataSourceSummary>(`/api/data-sources/${dataSourceId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteDataSource(dataSourceId: string): Promise<void> {
  await request<unknown>(`/api/data-sources/${dataSourceId}`, {
    method: "DELETE",
  });
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

export function syncDataSourceDatabases(
  dataSourceId: string,
): Promise<DataSourceDatabaseSyncResult> {
  return request<DataSourceDatabaseSyncResult>(
    `/api/data-sources/${dataSourceId}/databases/sync`,
    { method: "POST" },
  );
}

export function createDataSourceDatabase(
  dataSourceId: string,
  payload: DataSourceDatabasePayload,
): Promise<DataSourceDatabaseSummary> {
  return request<DataSourceDatabaseSummary>(
    `/api/data-sources/${dataSourceId}/databases`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export function updateDataSourceDatabase(
  dataSourceId: string,
  databaseId: string,
  payload: DataSourceDatabasePayload,
): Promise<DataSourceDatabaseSummary> {
  return request<DataSourceDatabaseSummary>(
    `/api/data-sources/${dataSourceId}/databases/${databaseId}`,
    { method: "PUT", body: JSON.stringify(payload) },
  );
}

export async function deleteDataSourceDatabase(
  dataSourceId: string,
  databaseId: string,
): Promise<void> {
  await request<unknown>(
    `/api/data-sources/${dataSourceId}/databases/${databaseId}`,
    { method: "DELETE" },
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

export function replaceProjectDatabases(
  projectId: string,
  databaseIds: string[],
  mcpAliases: Record<string, string> = {},
): Promise<ProjectDataSourceOptions> {
  return request<ProjectDataSourceOptions>(`/api/projects/${projectId}/databases`, {
    method: "PUT",
    body: JSON.stringify({ database_ids: databaseIds, mcp_aliases: mcpAliases }),
  });
}

export function updateProjectDatabaseAlias(
  projectId: string,
  linkId: string,
  mcpAlias: string,
): Promise<ProjectDatabaseLinkSummary> {
  return request<ProjectDatabaseLinkSummary>(
    `/api/projects/${projectId}/databases/${linkId}/mcp-alias`,
    {
      method: "PATCH",
      body: JSON.stringify({ mcp_alias: mcpAlias }),
    },
  );
}

export function createDatabaseProjectLink(
  databaseId: string,
  payload: ProjectDatabaseLinkPayload,
): Promise<ProjectDatabaseLinkSummary> {
  return request<ProjectDatabaseLinkSummary>(
    `/api/data-sources/databases/${databaseId}/projects`,
    { method: "POST", body: JSON.stringify(payload) },
  );
}

export async function deleteDatabaseProjectLink(
  databaseId: string,
  linkId: string,
): Promise<void> {
  await request<unknown>(
    `/api/data-sources/databases/${databaseId}/projects/${linkId}`,
    { method: "DELETE" },
  );
}
