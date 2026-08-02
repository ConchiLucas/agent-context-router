import type { ProjectSummary } from "@/lib/types";
import { assertBrowserApiRequestAllowed } from "@/lib/browser-api-policy";

export type RuntimeMode = "fast" | "full";

export interface RuntimeConfigFile {
  id: string;
  relative_path: string;
  content: string;
  executable: boolean;
  created_at: string;
  updated_at: string;
}

export interface RuntimeConfigMode {
  mode: RuntimeMode;
  files: RuntimeConfigFile[];
  updated_at: string | null;
}

export interface ProjectRuntimeConfig {
  project: ProjectSummary;
  fast: RuntimeConfigMode;
  full: RuntimeConfigMode;
}

export type RuntimeRunStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface RuntimeRunSummary {
  id: string;
  project_id: string;
  mode: RuntimeMode;
  trigger: "ui" | "mcp";
  status: RuntimeRunStatus;
  snapshot_id: string;
  materialized_path: string;
  project_root: string;
  entry_file: string;
  changed_files: string[];
  decision_reason: string;
  exit_code: number | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RuntimeRunLog {
  run_id: string;
  status: RuntimeRunStatus;
  content: string;
  truncated: boolean;
}

export interface WorkspaceDeployChangeSummary {
  additions: number;
  updates: number;
  deletions: number;
}

export interface WorkspaceDeployProfilePreview {
  owner: string;
  mode: "start" | RuntimeMode;
  file_count: number;
  changes: WorkspaceDeployChangeSummary;
}

export interface WorkspaceDeploySyncPreview {
  valid: boolean;
  source_root: string;
  digest: string;
  profiles: WorkspaceDeployProfilePreview[];
  total: WorkspaceDeployChangeSummary;
  synchronized: boolean;
}

const configuredBase =
  process.env.NEXT_PUBLIC_CONTEXT_ROUTER_API_URL ??
  "http://127.0.0.1:49173";
const normalizedBase = configuredBase.replace(/\/+$/, "");
const apiBase = normalizedBase.endsWith("/api")
  ? normalizedBase
  : `${normalizedBase}/api`;

async function runtimeRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  assertBrowserApiRequestAllowed(`/api${path}`, init?.method);
  const response = await fetch(`${apiBase}${path}`, {
    ...init,
    cache: "no-store",
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

export function getProjectRuntimeConfig(
  projectId: string,
): Promise<ProjectRuntimeConfig> {
  return runtimeRequest<ProjectRuntimeConfig>(
    `/projects/${encodeURIComponent(projectId)}/runtime-config`,
  );
}

export function listProjectRuntimeRuns(
  projectId: string,
): Promise<RuntimeRunSummary[]> {
  return runtimeRequest<RuntimeRunSummary[]>(
    `/projects/${encodeURIComponent(projectId)}/runtime-runs`,
  );
}

export function getProjectRuntimeRun(
  projectId: string,
  runId: string,
): Promise<RuntimeRunSummary> {
  return runtimeRequest<RuntimeRunSummary>(
    `/projects/${encodeURIComponent(projectId)}/runtime-runs/${encodeURIComponent(runId)}`,
  );
}

export function getProjectRuntimeRunLog(
  projectId: string,
  runId: string,
): Promise<RuntimeRunLog> {
  return runtimeRequest<RuntimeRunLog>(
    `/projects/${encodeURIComponent(projectId)}/runtime-runs/${encodeURIComponent(runId)}/log`,
  );
}

export function previewWorkspaceDeploySync(
  workspaceId: string,
): Promise<WorkspaceDeploySyncPreview> {
  return runtimeRequest<WorkspaceDeploySyncPreview>(
    `/workspaces/${encodeURIComponent(workspaceId)}/runtime-config/sync-preview`,
    { method: "POST" },
  );
}

export function commitWorkspaceDeploySync(
  workspaceId: string,
  expectedDigest: string,
): Promise<WorkspaceDeploySyncPreview> {
  return runtimeRequest<WorkspaceDeploySyncPreview>(
    `/workspaces/${encodeURIComponent(workspaceId)}/runtime-config/sync`,
    {
      method: "POST",
      body: JSON.stringify({ expected_digest: expectedDigest }),
    },
  );
}
