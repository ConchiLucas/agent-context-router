import assert from "node:assert/strict";
import test from "node:test";

import { eventDurationMs, readDocumentIds } from "./task-trace";
import type { TraceEvent } from "./types";

const events: TraceEvent[] = [
  {
    id: "prepare-1",
    event_type: "prepare",
    payload: { duration_ms: 12.45 },
    created_at: "2026-07-19T08:00:00Z",
  },
  {
    id: "read-1",
    event_type: "read",
    payload: { document_id: "architecture", duration_ms: 3 },
    created_at: "2026-07-19T08:00:01Z",
  },
  {
    id: "read-2",
    event_type: "read",
    payload: { document_id: "runbook", duration_ms: "invalid" },
    created_at: "2026-07-19T08:00:02Z",
  },
];

test("readDocumentIds returns only documents actually read by MCP", () => {
  assert.deepEqual(readDocumentIds(events), new Set(["architecture", "runbook"]));
});

test("eventDurationMs accepts only numeric durations", () => {
  assert.equal(eventDurationMs(events[0]), 12.45);
  assert.equal(eventDurationMs(events[2]), null);
});
