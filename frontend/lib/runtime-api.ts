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

export type RuntimeOperationStatus =
  | "queued"
  | "leased"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export interface RuntimeOperationStep {
  id: string;
  sequence: number;
  owner_type: "workspace" | "project";
  owner_id: string;
  mode: RuntimeMode | "start";
  status: "queued" | "running" | "succeeded" | "failed" | "skipped" | "cancelled";
  changed_files: string[];
  decision_reason: string;
  exit_code: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  log: string;
  log_truncated: boolean;
}

export interface RuntimeOperationSummary {
  id: string;
  task_id: number | null;
  workspace_id: string;
  kind: "apply_changes" | "start_workspace" | "project_update";
  trigger: "mcp" | "api" | "ui";
  status: RuntimeOperationStatus;
  changed_files: string[];
  current_step: number;
  runner_id: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  steps: RuntimeOperationStep[];
}

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

export function executeProjectRuntimeConfig(
  projectId: string,
  mode: RuntimeMode,
): Promise<RuntimeOperationSummary> {
  return runtimeRequest<RuntimeOperationSummary>(
    `/projects/${encodeURIComponent(projectId)}/runtime-config/${mode}/execute`,
    { method: "POST" },
  );
}

export function getWorkspaceRuntimeOperation(
  workspaceId: string,
  operationId: string,
): Promise<RuntimeOperationSummary> {
  return runtimeRequest<RuntimeOperationSummary>(
    `/workspaces/${encodeURIComponent(workspaceId)}/runtime-operations/${encodeURIComponent(operationId)}?log_characters=12000`,
  );
}

export function getWorkspaceRuntimeRunnerStatus(
  workspaceId: string,
): Promise<{ available: boolean }> {
  return runtimeRequest<{ available: boolean }>(
    `/workspaces/${encodeURIComponent(workspaceId)}/runtime-runner-status`,
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
