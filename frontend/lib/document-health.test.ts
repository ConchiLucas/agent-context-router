import assert from "node:assert/strict";
import test from "node:test";

import { mappingStatusLabel, syncSummaryText } from "./document-health";

test("mappingStatusLabel exposes actionable project states", () => {
  assert.equal(mappingStatusLabel("not_mapped"), "Not mapped");
  assert.equal(mappingStatusLabel("not_synced"), "Sync required");
  assert.equal(mappingStatusLabel("ready"), "Ready");
  assert.equal(mappingStatusLabel("invalid"), "Invalid mapping");
  assert.equal(mappingStatusLabel("sync_failed"), "Sync failed");
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
