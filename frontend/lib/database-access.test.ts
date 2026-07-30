import assert from "node:assert/strict";
import test from "node:test";

import {
  buildTaskContextTimeline,
  supportsConnectionTest,
} from "./database-access";

test("uses backend capabilities to decide whether connection testing is available", () => {
  assert.equal(
    supportsConnectionTest({
      engine: "clickhouse",
      configurable: true,
      discoverable: true,
      searchable: true,
      queryable: true,
    }),
    true,
  );
  assert.equal(
    supportsConnectionTest({
      engine: "oracle",
      configurable: true,
      discoverable: false,
      searchable: false,
      queryable: false,
    }),
    false,
  );
});

test("merges document and database calls into a chronological timeline", () => {
  const timeline = buildTaskContextTimeline(
    [
      {
        callNumber: 1,
        readCallId: 10,
        createdAt: "2026-07-23T10:02:00Z",
        steps: [],
      },
    ],
    [
      {
        database_call_id: 20,
        operation: "search_objects",
        database: "analytics",
        engine: "clickhouse",
        status: "ok",
        created_at: "2026-07-23T10:01:00Z",
      },
    ],
  );

  assert.deepEqual(
    timeline.map((item) => ({ kind: item.kind, eventNumber: item.eventNumber })),
    [
      { kind: "database", eventNumber: 1 },
      { kind: "read", eventNumber: 2 },
    ],
  );
});
