import type { WorkspaceSummary } from "./types";

type WorkspaceSummaryRequest = (
  workspaceId: string,
) => Promise<WorkspaceSummary>;

export interface WorkspaceRefreshResult {
  summary: WorkspaceSummary | null;
  error: string | null;
}

export async function runWorkspaceRefresh(
  workspaceId: string,
  refresh: WorkspaceSummaryRequest,
  recover: WorkspaceSummaryRequest,
): Promise<WorkspaceRefreshResult> {
  try {
    return {
      summary: await refresh(workspaceId),
      error: null,
    };
  } catch (requestError) {
    let summary: WorkspaceSummary | null = null;
    try {
      summary = await recover(workspaceId);
    } catch {
      // Preserve the refresh error when the recovery read is also unavailable.
    }
    return {
      summary,
      error:
        requestError instanceof Error
          ? requestError.message
          : String(requestError),
    };
  }
}

export function setWorkspaceRefreshError(
  errors: Readonly<Record<string, string>>,
  workspaceId: string,
  message: string,
): Record<string, string> {
  return { ...errors, [workspaceId]: message };
}

export function clearWorkspaceRefreshError(
  errors: Readonly<Record<string, string>>,
  workspaceId: string,
): Record<string, string> {
  const next = { ...errors };
  delete next[workspaceId];
  return next;
}

export function startWorkspaceRefresh(
  refreshingWorkspaceIds: ReadonlySet<string>,
  workspaceId: string,
): Set<string> {
  const next = new Set(refreshingWorkspaceIds);
  next.add(workspaceId);
  return next;
}

export function finishWorkspaceRefresh(
  refreshingWorkspaceIds: ReadonlySet<string>,
  workspaceId: string,
): Set<string> {
  const next = new Set(refreshingWorkspaceIds);
  next.delete(workspaceId);
  return next;
}

export function replaceWorkspaceSummary(
  workspaces: readonly WorkspaceSummary[],
  refreshed: WorkspaceSummary,
): WorkspaceSummary[] {
  return workspaces.map((workspace) =>
    workspace.id === refreshed.id ? refreshed : workspace,
  );
}
