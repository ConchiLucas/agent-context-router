import type {
  ChainAnalyticsOverview,
  ContextTaskReadHistory,
  ContextTaskSummary,
  DatabaseEnvironment,
  DocumentDetail,
  DocumentReadStatItem,
  DocumentReadTaskItem,
  DocumentTreeNode,
  McpIntegrationInfo,
  McpEnvironment,
  McpEnvironmentToolDefault,
  McpIntegrationTestResult,
  McpToolsListResult,
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
  WorkspaceEnvironmentList,
  WorkspaceContainer,
  WorkspaceContainerBulkAction,
  WorkspaceContainerBulkActionResult,
  WorkspaceSummary,
  WorkspaceMcpEnvironmentDefaults,
  WorkspaceNacosProfiles,
  WorkspaceSharedFilesResult,
  SystemGuideDetail,
  SystemGuideWrite,
  TableRelationDetail,
  TableRelationStatus,
  TableRelationTableDetail,
  TableRelationTableList,
  TableRelationTableUpdates,
  TableRelationTableWrites,
  TableRelationMcpPreview,
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

export function listWorkspaceContainers(
  workspaceId: string,
): Promise<WorkspaceContainer[]> {
  return request<WorkspaceContainer[]>(
    `/api/workspaces/${workspaceId}/containers`,
    { cache: "no-store" },
  );
}

export function getWorkspaceContainerLogStreamUrl(
  workspaceId: string,
  containerId: string,
): string {
  return `${API_URL}/api/workspaces/${encodeURIComponent(workspaceId)}/containers/${encodeURIComponent(containerId)}/logs/stream`;
}

export function runWorkspaceContainerBulkAction(
  workspaceId: string,
  action: WorkspaceContainerBulkAction,
  projectKind: "backend" | "frontend",
): Promise<WorkspaceContainerBulkActionResult> {
  return request<WorkspaceContainerBulkActionResult>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/containers/bulk-action`,
    {
      method: "POST",
      body: JSON.stringify({ action, project_kind: projectKind }),
    },
  );
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
  environment?: string,
): Promise<WorkspaceDataSourceSummary> {
  const query = environment
    ? `?environment=${encodeURIComponent(environment)}`
    : "";
  return request<WorkspaceDataSourceSummary>(
    `/api/workspaces/${workspaceId}/data-source-summary${query}`,
  );
}

export function getWorkspaceEnvironments(
  workspaceId: string,
): Promise<WorkspaceEnvironmentList> {
  return request<WorkspaceEnvironmentList>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/environments`,
    { cache: "no-store" },
  );
}

export function getWorkspaceNacosProfiles(
  workspaceId: string,
): Promise<WorkspaceNacosProfiles> {
  return request<WorkspaceNacosProfiles>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/nacos-profiles`,
    { cache: "no-store" },
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

export function getWorkspaceMcpEnvironmentDefaults(
  workspaceId: string,
): Promise<WorkspaceMcpEnvironmentDefaults> {
  return request<WorkspaceMcpEnvironmentDefaults>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/mcp-environment-defaults`,
    { cache: "no-store" },
  );
}

export function updateWorkspaceMcpEnvironmentDefault(
  workspaceId: string,
  toolName: string,
  environment: McpEnvironment,
): Promise<McpEnvironmentToolDefault> {
  return request<McpEnvironmentToolDefault>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/mcp-environment-defaults/${encodeURIComponent(toolName)}`,
    {
      method: "PUT",
      body: JSON.stringify({ environment }),
    },
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

export function fetchChainAnalyticsOverview(params?: {
  workspace_id?: string;
  hours?: number;
}): Promise<ChainAnalyticsOverview> {
  const searchParams = new URLSearchParams();
  if (params?.workspace_id) {
    searchParams.set("workspace_id", params.workspace_id);
  }
  if (params?.hours) {
    searchParams.set("hours", params.hours.toString());
  }
  const queryStr = searchParams.toString();
  const path = `/api/document-chain-analytics${queryStr ? `?${queryStr}` : ""}`;
  return request<ChainAnalyticsOverview>(path, { cache: "no-store" });
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

export function listMcpTools(): Promise<McpToolsListResult> {
  return request<McpToolsListResult>("/api/mcp/integration/tools", {
    cache: "no-store",
  });
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

export function getTableRelationStatus(
  workspaceId: string,
): Promise<TableRelationStatus> {
  return request<TableRelationStatus>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/status`,
  );
}

export function listTableRelationTables(
  workspaceId: string,
  options: { onlyRelated?: boolean; databaseKey?: string; limit?: number } = {},
): Promise<TableRelationTableList> {
  const params = new URLSearchParams({
    only_related: String(options.onlyRelated ?? false),
    limit: String(options.limit ?? 500),
  });
  if (options.databaseKey) params.set("database_key", options.databaseKey);
  return request<TableRelationTableList>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/tables?${params.toString()}`,
  );
}

export function getTableRelationDetail(
  workspaceId: string,
  table: { databaseKey: string; schemaName: string; tableName: string },
): Promise<TableRelationTableDetail> {
  const params = new URLSearchParams({
    database_key: table.databaseKey,
    schema_name: table.schemaName,
    table_name: table.tableName,
  });
  return request<TableRelationTableDetail>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/table?${params.toString()}`,
  );
}

/**
 * The evidence behind one relation, fetched when a row is opened rather than with
 * the table: the counts and queries behind a verdict are far larger than the row
 * that summarises it, and most rows are never opened.
 *
 * The table travels with the request because the two cardinalities are stated
 * from an end, and the panel has to state them from the end the row did.
 */
export function getTableRelationEvidence(
  workspaceId: string,
  relation: {
    edgeId: string;
    databaseKey: string;
    schemaName: string;
    tableName: string;
  },
): Promise<TableRelationDetail> {
  const params = new URLSearchParams({
    edge_id: relation.edgeId,
    database_key: relation.databaseKey,
    schema_name: relation.schemaName,
    table_name: relation.tableName,
  });
  return request<TableRelationDetail>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/relation?${params.toString()}`,
  );
}

export function getTableRelationWrites(
  workspaceId: string,
  table: { databaseKey: string; schemaName: string; tableName: string },
): Promise<TableRelationTableWrites> {
  const params = new URLSearchParams({
    database_key: table.databaseKey,
    schema_name: table.schemaName,
    table_name: table.tableName,
  });
  return request<TableRelationTableWrites>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/table/writes?${params.toString()}`,
  );
}

export function getTableRelationUpdates(
  workspaceId: string,
  table: { databaseKey: string; schemaName: string; tableName: string },
): Promise<TableRelationTableUpdates> {
  const params = new URLSearchParams({
    database_key: table.databaseKey,
    schema_name: table.schemaName,
    table_name: table.tableName,
  });
  return request<TableRelationTableUpdates>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/table/updates?${params.toString()}`,
  );
}

export function getTableRelationMcpPreview(
  workspaceId: string,
  table: { databaseKey: string; schemaName: string; tableName: string },
  options?: { includeEvidence?: boolean },
): Promise<TableRelationMcpPreview> {
  const params = new URLSearchParams({
    database_key: table.databaseKey,
    schema_name: table.schemaName,
    table_name: table.tableName,
    include_evidence: String(options?.includeEvidence ?? true),
  });
  return request<TableRelationMcpPreview>(
    `/api/workspaces/${encodeURIComponent(workspaceId)}/table-relations/table/mcp?${params.toString()}`,
  );
}
