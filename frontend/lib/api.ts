import type {
  ContextTaskReadHistory,
  ContextTaskSummary,
  DocumentDetail,
  DocumentTreeNode,
  McpIntegrationInfo,
  McpIntegrationTestResult,
  PrepareTaskContextResult,
  ProjectCreate,
  ProjectSummary,
  ProjectUpdate,
} from "@/lib/types";

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

export function listProjects(): Promise<ProjectSummary[]> {
  return request<ProjectSummary[]>("/api/projects");
}

export function createProject(payload: ProjectCreate): Promise<ProjectSummary> {
  return request<ProjectSummary>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function refreshProject(projectId: string): Promise<ProjectSummary> {
  return request<ProjectSummary>(`/api/projects/${projectId}/refresh`, {
    method: "POST",
  });
}

export function updateProject(
  projectId: string,
  payload: ProjectUpdate,
): Promise<ProjectSummary> {
  return request<ProjectSummary>(`/api/projects/${projectId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function setProjectEnabled(
  projectId: string,
  enabled: boolean,
): Promise<ProjectSummary> {
  return request<ProjectSummary>(`/api/projects/${projectId}/enabled`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  await request<unknown>(`/api/projects/${projectId}`, { method: "DELETE" });
}

export function getProjectTree(projectId: string): Promise<DocumentTreeNode> {
  return request<DocumentTreeNode>(`/api/projects/${projectId}/tree`);
}

export function getDocumentDetail(
  projectId: string,
  documentId: string,
): Promise<DocumentDetail> {
  return request<DocumentDetail>(
    `/api/projects/${projectId}/documents/${documentId}`,
  );
}

export function prepareProjectPreview(
  projectId: string,
): Promise<PrepareTaskContextResult> {
  return request<PrepareTaskContextResult>(
    `/api/projects/${projectId}/prepare-preview`,
    { method: "POST" },
  );
}

export function listProjectTasks(
  projectId: string,
): Promise<ContextTaskSummary[]> {
  return request<ContextTaskSummary[]>(`/api/projects/${projectId}/tasks`);
}

export function getTaskDocumentReads(
  taskId: number,
): Promise<ContextTaskReadHistory> {
  return request<ContextTaskReadHistory>(
    `/api/tasks/${taskId}/document-reads`,
  );
}

export function getMcpIntegration(): Promise<McpIntegrationInfo> {
  return request<McpIntegrationInfo>("/api/mcp/integration");
}

export function runMcpIntegrationTest(
  projectId: string,
): Promise<McpIntegrationTestResult> {
  return request<McpIntegrationTestResult>("/api/mcp/integration/tests", {
    method: "POST",
    body: JSON.stringify({ project_id: projectId }),
  });
}
