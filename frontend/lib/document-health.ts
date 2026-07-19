import type { SyncSummary } from "./types";

const MAPPING_STATUS_LABELS: Record<string, string> = {
  not_mapped: "Not mapped",
  not_synced: "Sync required",
  ready: "Ready",
  invalid: "Invalid mapping",
  sync_failed: "Sync failed",
};

export function mappingStatusLabel(status: string) {
  return MAPPING_STATUS_LABELS[status] ?? status;
}

export function syncSummaryText(summary: SyncSummary) {
  return [
    `${summary.indexed} indexed`,
    `${summary.reachable} reachable`,
    `${summary.orphan} orphan`,
    `${summary.broken_links} broken`,
  ].join(" · ");
}
