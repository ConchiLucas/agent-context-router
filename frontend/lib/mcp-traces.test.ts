import assert from "node:assert/strict";
import test from "node:test";

import {
  INTERNAL_MCP_TOOL_NAMES,
  buildMcpTraceListPath,
  buildTraceDocumentCallNumbers,
  buildTraceGraphRows,
  documentsForTraceCall,
  filterMcpTraces,
  internalTraceCalls,
  isInternalMcpToolName,
  sortTraceCalls,
  statusQueryForTraceFilter,
  traceCallResultSummary,
  traceCompletenessLabel,
  traceWarningMessages,
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
      toolName: "read_context_document",
      status: "error",
      keyword: "订单 路由",
      limit: 500,
    }),
    "/api/mcp-traces?project_id=project%2Fwith+space&agent_name=codex&tool_name=read_context_document&status=error&keyword=%E8%AE%A2%E5%8D%95+%E8%B7%AF%E7%94%B1&limit=100",
  );
  assert.equal(buildMcpTraceListPath(), "/api/mcp-traces");
});

test("maps task health filters to supported server-side call status queries", () => {
  assert.equal(statusQueryForTraceFilter("running"), "running");
  assert.equal(statusQueryForTraceFilter("error"), "error");
  assert.equal(statusQueryForTraceFilter("ok"), undefined);
  assert.equal(statusQueryForTraceFilter("all"), undefined);
});

test("maps trace completeness and warning codes to concise Chinese messages", () => {
  assert.equal(traceCompletenessLabel("complete"), "完整");
  assert.equal(traceCompletenessLabel("running"), "运行中");
  assert.equal(traceCompletenessLabel("partial"), "可能不完整");
  assert.deepEqual(
    traceWarningMessages([
      "running_calls",
      "legacy_calls",
      "unlinked_document_reads",
      "unlinked_database_calls",
      "missing_prepare_call",
    ]),
    [
      "仍有内部工具调用正在运行，链路内容会继续更新。",
      "包含升级前的历史记录，部分调用细节可能缺失。",
      "部分文档读取记录无法关联到对应工具调用。",
      "部分数据库访问记录无法关联到对应工具调用。",
      "缺少 prepare_task_context 调用记录，任务起点可能未完整落库。",
    ],
  );
  assert.deepEqual(
    traceWarningMessages(["future_warning", "future_warning"]),
    ["链路包含无法完整还原的记录。"],
  );
});

test("keeps the ten current and three historical Context Router tools", () => {
  assert.deepEqual(INTERNAL_MCP_TOOL_NAMES, [
    "prepare_task_context",
    "read_task_context",
    "read_middleware_context",
    "search_context_documents",
    "read_context_document",
    "search_database_objects",
    "execute_database_query",
    "apply_workspace_changes",
    "start_workspace",
    "get_workspace_operation",
    "apply_project_changes",
    "get_project_operation",
    "prepare_table_relation_context",
  ]);

  const calls = [
    call({
      tool_call_id: 1,
      sequence: 1,
      tool_name: "prepare_task_context",
    }),
    call({
      tool_call_id: 2,
      sequence: 2,
      tool_name: "search_context_documents",
    }),
    call({
      tool_call_id: 3,
      sequence: 3,
      tool_name: "execute_database_query",
      source: "legacy",
    }),
    call({
      tool_call_id: 4,
      sequence: 4,
      tool_name: "start_workspace",
    }),
    call({
      tool_call_id: 5,
      sequence: 5,
      tool_name: "read_context_document",
      source: "gateway",
    }),
    call({
      tool_call_id: 6,
      sequence: 6,
      tool_name: "github__search_code",
    }),
  ];

  assert.equal(isInternalMcpToolName("search_context_documents"), true);
  assert.equal(isInternalMcpToolName("search_database_objects"), true);
  assert.equal(isInternalMcpToolName("start_workspace"), true);
  assert.equal(isInternalMcpToolName("github__search_code"), false);
  assert.deepEqual(
    internalTraceCalls(calls).map((item) => item.tool_call_id),
    [1, 2, 3, 4],
  );
});

test("summarizes document search results without exposing result payloads", () => {
  assert.equal(
    traceCallResultSummary(
      call({
        tool_call_id: 1,
        sequence: 1,
        tool_name: "search_context_documents",
        result_summary: {
          returned_count: 3,
          truncated: false,
          max_relevance: 0.92,
        },
      }),
    ),
    "返回 3 个文档",
  );
  assert.equal(
    traceCallResultSummary(
      call({
        tool_call_id: 2,
        sequence: 2,
        tool_name: "search_context_documents",
        result_summary: { returned_count: -1 },
      }),
    ),
    null,
  );
  assert.equal(
    traceCallResultSummary(
      call({
        tool_call_id: 3,
        sequence: 3,
        tool_name: "execute_database_query",
        result_summary: { returned_count: 3 },
      }),
    ),
    null,
  );
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

test("filters task summaries by aggregate task health", () => {
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
      trace_status: "complete",
      warnings: [],
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
      trace_status: "partial",
      warnings: ["legacy_calls"],
    },
  ];

  assert.deepEqual(
    filterMcpTraces(traces, {
      status: "error",
    }).map((trace) => trace.task_id),
    [12],
  );
  assert.deepEqual(
    filterMcpTraces(traces, {
      status: "ok",
    }).map((trace) => trace.task_id),
    [11],
  );
  assert.deepEqual(
    filterMcpTraces(traces, {
      status: "running",
    }).map((trace) => trace.task_id),
    [11, 12],
  );
});
