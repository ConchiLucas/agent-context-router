import assert from "node:assert/strict";
import test from "node:test";

import { sortInterfacesByLastRequest } from "./interface-forwarding-order";

test("sorts requested interfaces newest first and keeps unrequested interfaces last", () => {
  const items = [
    { path: "/beta", method: "GET", last_requested_at: null },
    { path: "/older", method: "POST", last_requested_at: "2026-08-22T10:00:00+08:00" },
    { path: "/newer", method: "POST", last_requested_at: "2026-08-22T11:00:00+08:00" },
    { path: "/alpha", method: "GET", last_requested_at: null },
  ];

  assert.deepEqual(
    sortInterfacesByLastRequest(items).map((item) => item.path),
    ["/newer", "/older", "/alpha", "/beta"],
  );
});

test("does not mutate the overview response array", () => {
  const items = [
    { path: "/second", method: "GET", last_requested_at: null },
    { path: "/first", method: "GET", last_requested_at: null },
  ];

  sortInterfacesByLastRequest(items);

  assert.deepEqual(items.map((item) => item.path), ["/second", "/first"]);
});
