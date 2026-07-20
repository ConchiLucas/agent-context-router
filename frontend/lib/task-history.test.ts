import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDocumentCallNumbers,
  buildTaskReadRows,
  buildTaskReadSteps,
} from "./task-history";

test("flattens read calls into one global sequence", () => {
  const steps = buildTaskReadSteps([
    {
      read_call_id: 41,
      created_at: "2026-07-21T01:00:00Z",
      documents: [
        { position: 1, document_id: "a", path: "a.md", status: "ok" },
        { position: 2, document_id: "b", path: "b.md", status: "ok" },
      ],
    },
    {
      read_call_id: 42,
      created_at: "2026-07-21T01:01:00Z",
      documents: [
        { position: 1, document_id: "c", path: "c.md", status: "error" },
      ],
    },
  ]);

  assert.deepEqual(
    steps.map((step) => ({
      sequence: step.sequence,
      callNumber: step.callNumber,
      readCallId: step.readCallId,
      position: step.document.position,
    })),
    [
      { sequence: 1, callNumber: 1, readCallId: 41, position: 1 },
      { sequence: 2, callNumber: 1, readCallId: 41, position: 2 },
      { sequence: 3, callNumber: 2, readCallId: 42, position: 1 },
    ],
  );
});

test("keeps documents from one MCP call in the same display row", () => {
  const rows = buildTaskReadRows([
    {
      read_call_id: 41,
      created_at: "2026-07-21T01:00:00Z",
      documents: [
        { position: 1, document_id: "a", status: "ok" },
        { position: 2, document_id: "b", status: "ok" },
      ],
    },
    {
      read_call_id: 42,
      created_at: "2026-07-21T01:01:00Z",
      documents: [{ position: 1, document_id: "c", status: "ok" }],
    },
  ]);

  assert.deepEqual(
    rows.map((row) => ({
      callNumber: row.callNumber,
      documents: row.steps.map((step) => step.document.document_id),
      sequences: row.steps.map((step) => step.sequence),
    })),
    [
      { callNumber: 1, documents: ["a", "b"], sequences: [1, 2] },
      { callNumber: 2, documents: ["c"], sequences: [3] },
    ],
  );
});

test("groups tree badges by MCP call instead of global document order", () => {
  const callNumbers = buildDocumentCallNumbers([
    {
      read_call_id: 41,
      created_at: "2026-07-21T01:00:00Z",
      documents: [
        { position: 1, document_id: "a", status: "ok" },
        { position: 2, document_id: "b", status: "ok" },
        { position: 3, document_id: "a", status: "ok" },
      ],
    },
    {
      read_call_id: 42,
      created_at: "2026-07-21T01:01:00Z",
      documents: [
        { position: 1, document_id: "c", status: "error" },
        { position: 2, document_id: "a", status: "ok" },
      ],
    },
  ]);

  assert.deepEqual([...callNumbers], [
    ["a", [1, 2]],
    ["b", [1]],
    ["c", [2]],
  ]);
});
