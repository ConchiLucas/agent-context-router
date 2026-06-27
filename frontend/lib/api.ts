import type {
  DocumentListResponse,
  ProjectDetail,
  ProjectListResponse,
  TraceDetail,
  TraceListResponse,
} from "@/lib/types";

const API_BASE_URL = process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ?? "http://127.0.0.1:8000";

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      Accept: "application/json",
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export async function getProjects() {
  return fetchJson<ProjectListResponse>("/api/projects");
}

export async function getProject(slug: string) {
  return fetchJson<ProjectDetail>(`/api/projects/${slug}`);
}

export async function getDocuments(filters: Record<string, string | undefined> = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return fetchJson<DocumentListResponse>(`/api/documents${query ? `?${query}` : ""}`);
}

export async function getTraces() {
  return fetchJson<TraceListResponse>("/api/traces");
}

export async function getTrace(traceId: string) {
  return fetchJson<TraceDetail>(`/api/traces/${traceId}`);
}

export function contextRouterApiUrl() {
  return API_BASE_URL;
}
