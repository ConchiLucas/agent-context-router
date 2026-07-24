import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMcpTraceListPath,
  buildTraceDocumentCallNumbers,
  buildTraceGraphRows,
  documentsForTraceCall,
  filterMcpTraces,
  sortTraceCalls,
} from "./mcp-traces";
import type { McpTraceSummary, McpTraceToolCall } from "./types";

function call(
  overrides: Partial<McpTraceToolCall> & Pick<McpTraceToolCall, "tool_call_id" | "sequence">,
): McpTraceToolCall {
  return {
    server_name: "context-router",
    tool_name: "read_context_document",
    source: "server",
    status: "ok",
    started_at: "2026-07-24T01:00:00Z",
    artifacts: [],
    ...overrides,
  };
}

test("builds the trace list query for project-scoped navigation", () => {
  assert.equal(
    buildMcpTraceListPath({
      projectId: "project/with space",
      agentName: "codex",
      status: "error",
      limit: 500,
    }),
    "/api/mcp-traces?project_id=project%2Fwith+space&agent_name=codex&status=error&limit=100",
  );
  assert.equal(buildMcpTraceListPath(), "/api/mcp-traces");
});

test("orders calls by server sequence and uses id as a deterministic tie breaker", () => {
  const calls = [
    call({ tool_call_id: 9, sequence: 2 }),
    call({ tool_call_id: 8, sequence: 2 }),
    call({ tool_call_id: 7, sequence: 1 }),
  ];

  assert.deepEqual(
    sortTraceCalls(calls).map((item) => item.tool_call_id),
    [7, 8, 9],
  );
});

test("builds explicit parent depth without inventing links for flat calls", () => {
  const rows = buildTraceGraphRows([
    call({ tool_call_id: 1, sequence: 1 }),
    call({ tool_call_id: 2, sequence: 2 }),
    call({ tool_call_id: 3, sequence: 3, parent_tool_call_id: 1 }),
    call({ tool_call_id: 4, sequence: 4, parent_tool_call_id: 3 }),
  ]);

  assert.deepEqual(
    rows.map((row) => ({
      sequence: row.call.sequence,
      depth: row.depth,
      parentSequence: row.parentSequence,
    })),
    [
      { sequence: 1, depth: 0, parentSequence: null },
      { sequence: 2, depth: 0, parentSequence: null },
      { sequence: 3, depth: 1, parentSequence: 1 },
      { sequence: 4, depth: 2, parentSequence: 3 },
    ],
  );
});

test("keeps documents from one read call together and marks tree by tool sequence", () => {
  const calls = [
    call({
      tool_call_id: 1,
      sequence: 4,
      artifacts: [
        {
          kind: "document_read",
          read_call_id: 21,
          documents: [
            { position: 2, document_id: "b", status: "ok" },
            { position: 1, document_id: "a", status: "ok" },
          ],
        },
      ],
    }),
    call({
      tool_call_id: 2,
      sequence: 7,
      artifacts: [
        {
          kind: "document_read",
          documents: [
            { position: 1, document_id: "a", status: "ok" },
            { position: 2, document_id: "c", status: "error" },
          ],
        },
      ],
    }),
  ];

  assert.deepEqual(
    documentsForTraceCall(calls[0]).map((document) => document.document_id),
    ["a", "b"],
  );
  assert.deepEqual([...buildTraceDocumentCallNumbers(calls)], [
    ["a", [4, 7]],
    ["b", [4]],
  ]);
});

test("filters task summaries across task metadata and health", () => {
  const traces: McpTraceSummary[] = [
    {
      task_id: 11,
      task: "检查订单",
      project_id: "project-a",
      project_name: "项目 A",
      cwd: "/work/a",
      agent_name: "codex",
      created_at: "2026-07-24T01:00:00Z",
      call_count: 3,
      error_count: 0,
      server_names: ["context-router"],
      last_activity_at: "2026-07-24T01:02:00Z",
    },
    {
      task_id: 12,
      task: "查询库存",
      project_id: "project-b",
      project_name: "项目 B",
      cwd: "/work/b",
      agent_name: "antigravity",
      created_at: "2026-07-24T02:00:00Z",
      call_count: 2,
      error_count: 1,
      server_names: ["context-router", "github"],
      last_activity_at: "2026-07-24T02:03:00Z",
    },
  ];

  assert.deepEqual(
    filterMcpTraces(traces, {
      query: "库存",
      agentName: "",
      serverName: "github",
      status: "error",
    }).map((trace) => trace.task_id),
    [12],
  );
  assert.deepEqual(
    filterMcpTraces(traces, {
      query: "项目 A",
      agentName: "codex",
      serverName: "",
      status: "ok",
    }).map((trace) => trace.task_id),
    [11],
  );
});
