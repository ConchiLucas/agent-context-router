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

export type DocumentHierarchyNode = {
  document: DocumentSummary;
  edgeLabel: string | null;
  isReference: boolean;
  children: DocumentHierarchyNode[];
};

export function buildDocumentHierarchy(
  documents: DocumentSummary[],
  project?: string,
): DocumentHierarchyNode | null {
  const documentById = new Map(documents.map((document) => [document.id, document]));
  const roots = documents
    .filter(
      (document) =>
        document.status === "active" &&
        document.is_reachable &&
        document.graph_depth === 1 &&
        document.doc_type === "agent_index",
    )
    .sort(
      (left, right) =>
        Number(right.project_slug === project) - Number(left.project_slug === project) ||
        left.source_path.localeCompare(right.source_path) ||
        left.id.localeCompare(right.id),
    );
  const root = roots[0];
  if (!root) return null;

  const expanded = new Set<string>([root.id]);

  function buildNode(
    document: DocumentSummary,
    edgeLabel: string | null,
    isReference = false,
  ): DocumentHierarchyNode {
    if (isReference) {
      return { document, edgeLabel, isReference: true, children: [] };
    }

    const links = document.links
      .filter((link) => !link.is_broken && link.target_document_id !== null)
      .sort(
        (left, right) =>
          left.sort_order - right.sort_order || left.target_path.localeCompare(right.target_path),
      );
    const children = links.flatMap((link) => {
      const target = documentById.get(link.target_document_id ?? "");
      if (!target || target.status !== "active" || !target.is_reachable) return [];

      const followsShortestDepth =
        document.graph_depth !== null && target.graph_depth === document.graph_depth + 1;
      const reference = !followsShortestDepth || expanded.has(target.id);
      if (!reference) expanded.add(target.id);
      return [buildNode(target, link.label, reference)];
    });

    return { document, edgeLabel, isReference: false, children };
  }

  return buildNode(root, null);
}

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
