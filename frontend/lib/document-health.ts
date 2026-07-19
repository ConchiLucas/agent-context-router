import type { DocumentLinkSummary, DocumentSummary, SyncSummary } from "./types";

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

export function mappingNoticeText(notice: string, mappingStatus: string) {
  return mappingStatus === "not_synced" ? notice : "";
}

export function syncSummaryText(summary: SyncSummary) {
  return [
    `${summary.indexed} indexed`,
    `${summary.reachable} reachable`,
    `${summary.orphan} orphan`,
    `${summary.broken_links} broken`,
  ].join(" · ");
}

export type DocumentDepthLevel = {
  depth: number;
  documents: DocumentSummary[];
};

export type BrokenDocumentLink = {
  source: DocumentSummary;
  link: DocumentLinkSummary;
};

export function groupDocumentsByDepth(documents: DocumentSummary[]) {
  const byDepth = new Map<number, DocumentSummary[]>();
  const orphans: DocumentSummary[] = [];
  const brokenLinks: BrokenDocumentLink[] = [];

  for (const document of documents) {
    if (document.is_reachable && document.graph_depth !== null) {
      const level = byDepth.get(document.graph_depth) ?? [];
      level.push(document);
      byDepth.set(document.graph_depth, level);
    } else {
      orphans.push(document);
    }
    for (const link of document.links.filter((item) => item.is_broken)) {
      brokenLinks.push({ source: document, link });
    }
  }

  const compareDocuments = (left: DocumentSummary, right: DocumentSummary) =>
    left.source_path.localeCompare(right.source_path) || left.id.localeCompare(right.id);
  const levels = [...byDepth.entries()]
    .sort(([left], [right]) => left - right)
    .map(([depth, levelDocuments]) => ({
      depth,
      documents: levelDocuments.sort(compareDocuments),
    }));
  orphans.sort(compareDocuments);
  brokenLinks.sort(
    (left, right) =>
      left.source.id.localeCompare(right.source.id) ||
      left.link.sort_order - right.link.sort_order ||
      left.link.target_path.localeCompare(right.link.target_path),
  );

  return { levels, orphans, brokenLinks };
}
