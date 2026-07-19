import assert from "node:assert/strict";
import test from "node:test";

import {
  groupDocumentsByDepth,
  mappingNoticeText,
  mappingStatusLabel,
  syncSummaryText,
} from "./document-health";
import type { DocumentSummary } from "./types";

test("mappingStatusLabel exposes actionable project states", () => {
  assert.equal(mappingStatusLabel("not_mapped"), "Not mapped");
  assert.equal(mappingStatusLabel("not_synced"), "Sync required");
  assert.equal(mappingStatusLabel("ready"), "Ready");
  assert.equal(mappingStatusLabel("invalid"), "Invalid mapping");
  assert.equal(mappingStatusLabel("sync_failed"), "Sync failed");
});

test("mappingNoticeText hides sync-required notice after the project is ready", () => {
  assert.equal(
    mappingNoticeText("Mapping saved. Sync required.", "not_synced"),
    "Mapping saved. Sync required.",
  );
  assert.equal(mappingNoticeText("Mapping saved. Sync required.", "ready"), "");
});

test("syncSummaryText includes reachable orphan and broken counts", () => {
  assert.equal(
    syncSummaryText({
      indexed: 8,
      reachable: 6,
      orphan: 2,
      broken_links: 1,
      pruned: 0,
    }),
    "8 indexed · 6 reachable · 2 orphan · 1 broken",
  );
});

test("groupDocumentsByDepth keeps every reachable depth and separates orphans", () => {
  const grouped = groupDocumentsByDepth([
    document("entry", true, 1),
    document("business", true, 2),
    document("schema", true, 3),
    document("orphan", false, null),
  ]);

  assert.deepEqual(
    grouped.levels.map((level) => level.depth),
    [1, 2, 3],
  );
  assert.deepEqual(
    grouped.levels.map((level) => level.documents.map((item) => item.id)),
    [["entry"], ["business"], ["schema"]],
  );
  assert.deepEqual(
    grouped.orphans.map((item) => item.id),
    ["orphan"],
  );
});

test("groupDocumentsByDepth returns broken links in stable source and link order", () => {
  const beta = document("beta", true, 2, [
    brokenLink("Z link", "docs/z.md", 2),
    brokenLink("A link", "docs/a.md", 1),
  ]);
  const alpha = document("alpha", true, 1, [brokenLink("Missing", "docs/missing.md", 0)]);

  const grouped = groupDocumentsByDepth([beta, alpha]);

  assert.deepEqual(
    grouped.brokenLinks.map(({ source, link }) => [source.id, link.label, link.target_path]),
    [
      ["alpha", "Missing", "docs/missing.md"],
      ["beta", "A link", "docs/a.md"],
      ["beta", "Z link", "docs/z.md"],
    ],
  );
});

function document(
  id: string,
  isReachable: boolean,
  graphDepth: number | null,
  links: DocumentSummary["links"] = [],
): DocumentSummary {
  return {
    id,
    project_slug: "orders",
    title: id,
    source_path: id === "entry" ? "AGENTS.md" : `docs/${id}.md`,
    area: null,
    doc_type: id === "entry" ? "agent_index" : "guide",
    tags: [],
    status: "active",
    is_reachable: isReachable,
    graph_depth: graphDepth,
    broken_link_count: links.filter((link) => link.is_broken).length,
    links,
  };
}

function brokenLink(label: string, targetPath: string, sortOrder: number) {
  return {
    target_document_id: null,
    target_path: targetPath,
    label,
    relation_type: "markdown_link",
    sort_order: sortOrder,
    is_broken: true,
  };
}
