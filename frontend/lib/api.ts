import type {
  DocumentDetail,
  DocumentListResponse,
  ProjectDetail,
  ProjectListResponse,
  TraceDetail,
  TraceListResponse,
  UsageCard,
  UsageCardListResponse,
} from "@/lib/types";

const PUBLIC_API_BASE_URL =
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ?? "http://127.0.0.1:8000";
const SERVER_API_BASE_URL =
  process.env.CONTEXT_ROUTER_INTERNAL_API_URL ?? PUBLIC_API_BASE_URL;

function apiBaseUrl() {
  return typeof window === "undefined" ? SERVER_API_BASE_URL : PUBLIC_API_BASE_URL;
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
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

async function sendJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export async function getProjects(options: { includeChildren?: boolean } = {}) {
  const params = new URLSearchParams();
  if (options.includeChildren) {
    params.set("include_children", "true");
  }
  const query = params.toString();
  return fetchJson<ProjectListResponse>(`/api/projects${query ? `?${query}` : ""}`);
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

export async function getDocument(documentId: string) {
  return fetchJson<DocumentDetail>(`/api/documents/${encodeURIComponent(documentId)}?untracked=true`);
}

export async function getTraces(filters: Record<string, string | undefined> = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) {
      params.set(key, value);
    }
  }
  const query = params.toString();
  return fetchJson<TraceListResponse>(`/api/traces${query ? `?${query}` : ""}`);
}

export async function getTrace(traceId: string) {
  return fetchJson<TraceDetail>(`/api/traces/${traceId}`);
}

export async function getUsageCards() {
  return fetchJson<UsageCardListResponse>("/api/usage/cards");
}

export async function createUsageCard(card: {
  title: string;
  description: string;
  content_markdown: string;
}) {
  return sendJson<UsageCard>("/api/usage/cards", "POST", card);
}

export async function updateUsageCard(
  slug: string,
  card: {
    title: string;
    description: string;
    content_markdown: string;
    sort_order?: number;
  }
) {
  return sendJson<UsageCard>(`/api/usage/cards/${encodeURIComponent(slug)}`, "PUT", card);
}

export async function deleteUsageCard(slug: string) {
  return sendJson<{ deleted: boolean }>(
    `/api/usage/cards/${encodeURIComponent(slug)}`,
    "DELETE"
  );
}

export function contextRouterApiUrl() {
  return apiBaseUrl();
}
