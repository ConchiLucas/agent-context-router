import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDatabasePayloadPath,
  databasePayloadDisplay,
  databasePayloadUnavailableMessage,
  isDatabaseMcpCall,
} from "./database-call-payload";
import type {
  McpDatabaseToolPayload,
  McpTraceToolCall,
} from "./types";

function traceCall(toolName: string): McpTraceToolCall {
  return {
    tool_call_id: 8,
    sequence: 2,
    server_name: "context-router",
    tool_name: toolName,
    source: "server",
    status: "ok",
    started_at: "2026-07-25T01:00:00Z",
    artifacts: [],
  };
}

function payload(
  overrides: Partial<McpDatabaseToolPayload> = {},
): McpDatabaseToolPayload {
  return {
    task_id: 3,
    tool_call_id: 8,
    tool_name: "execute_database_query",
    available: true,
    request_truncated: false,
    response_truncated: false,
    ...overrides,
  };
}

test("recognizes only database MCP calls", () => {
  assert.equal(isDatabaseMcpCall(traceCall("search_database_objects")), true);
  assert.equal(isDatabaseMcpCall(traceCall("execute_database_query")), true);
  assert.equal(isDatabaseMcpCall(traceCall("read_context_document")), false);
});

test("builds the lazy database payload detail path", () => {
  assert.equal(
    buildDatabasePayloadPath(90, 236),
    "/api/mcp-traces/90/calls/236/database-payload",
  );
});

test("separates SQL from the request JSON and builds copy text", () => {
  const display = databasePayloadDisplay(
    payload({
      request_payload: {
        task_id: 3,
        database: "uat_mtp",
        sql: "SELECT id FROM entrusted",
      },
    }),
    "request",
  );

  assert.equal(display.sql, "SELECT id FROM entrusted");
  assert.equal(display.json.includes('"sql"'), false);
  assert.equal(display.json.includes('"database": "uat_mtp"'), true);
  assert.equal(display.clipboard.startsWith("SELECT id FROM entrusted"), true);
});

test("maps unavailable payload reasons to explicit messages", () => {
  assert.equal(
    databasePayloadUnavailableMessage(
      payload({ available: false, reason: "not_captured" }),
    ),
    "该调用产生于详情采集功能上线前，没有保存出入参详情。",
  );
  assert.equal(
    databasePayloadUnavailableMessage(
      payload({ available: false, reason: "expired" }),
    ),
    "该调用的出入参详情已超过保留期限。",
  );
});
