import type {
  ContextTaskReadHistory,
  ContextTaskSummary,
  DocumentDetail,
  DocumentTreeNode,
  PrepareTaskContextResult,
  ProjectCreate,
  ProjectSummary,
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
