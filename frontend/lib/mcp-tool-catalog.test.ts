import assert from "node:assert/strict";
import test from "node:test";

import {
  LIVE_MCP_TOOL_NAMES,
  MCP_TOOL_DESCRIPTIONS_ZH,
  MCP_TOOL_GROUPS,
  displayMcpToolDescription,
  groupMcpTools,
  mcpToolName,
} from "./mcp-tool-catalog";

test("catalog covers the 26 live MCP tools without overlap", () => {
  const grouped = MCP_TOOL_GROUPS.flatMap((group) => [...group.tools]);
  assert.equal(LIVE_MCP_TOOL_NAMES.length, 26);
  assert.deepEqual([...grouped].sort(), [...LIVE_MCP_TOOL_NAMES].sort());
  assert.equal(new Set(grouped).size, LIVE_MCP_TOOL_NAMES.length);
  assert.equal(Object.keys(MCP_TOOL_DESCRIPTIONS_ZH).length, 26);
  for (const name of LIVE_MCP_TOOL_NAMES) {
    assert.ok(MCP_TOOL_DESCRIPTIONS_ZH[name].includes("。"));
  }
});

test("groupMcpTools keeps catalog group order and isolates unknown tools", () => {
  const tools = [
    { name: "execute_forwarding_request" },
    { name: "prepare_task_context" },
    { name: "future_tool" },
    { name: "read_table_relations" },
    { name: "search_forwarding_interfaces" },
  ];
  const grouped = groupMcpTools(tools, mcpToolName);
  assert.deepEqual(
    grouped.map((group) => group.id),
    ["context", "table-relations", "interfaces", "other"],
  );
  assert.deepEqual(
    grouped.flatMap((group) => group.tools.map((tool) => tool.name)),
    [
      "prepare_task_context",
      "read_table_relations",
      "search_forwarding_interfaces",
      "execute_forwarding_request",
      "future_tool",
    ],
  );
  assert.equal(
    displayMcpToolDescription({ name: "resolve_database_target" }),
    MCP_TOOL_DESCRIPTIONS_ZH.resolve_database_target,
  );
});
