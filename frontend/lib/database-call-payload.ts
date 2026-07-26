import type {
  McpDatabaseToolPayload,
  McpTraceToolCall,
} from "@/lib/types";

export type DatabasePayloadView = "request" | "response";

const DATABASE_MCP_TOOL_NAMES = new Set([
  "search_database_objects",
  "execute_database_query",
]);

const UNAVAILABLE_MESSAGES: Readonly<Record<string, string>> = {
  not_captured: "该调用产生于详情采集功能上线前，没有保存出入参详情。",
  expired: "该调用的出入参详情已超过保留期限。",
  capture_failed: "工具调用已完成，但服务端未能保存出入参详情。",
};

export function isDatabaseMcpCall(call: McpTraceToolCall): boolean {
  return DATABASE_MCP_TOOL_NAMES.has(call.tool_name);
}

export function buildDatabasePayloadPath(
  taskId: number,
  toolCallId: number,
): string {
  return `/api/mcp-traces/${taskId}/calls/${toolCallId}/database-payload`;
}

export function databasePayloadUnavailableMessage(
  payload: McpDatabaseToolPayload,
): string {
  if (payload.available) return "";
  if (payload.status === "pending") {
    return "服务端仍在采集这次调用的出入参详情，请稍后刷新链路。";
  }
  if (payload.status === "interrupted") {
    return "详情采集在服务重启前被中断，无法完整还原。";
  }
  return payload.reason
    ? (UNAVAILABLE_MESSAGES[payload.reason] ??
        "这次调用没有可展示的出入参详情。")
    : "这次调用没有可展示的出入参详情。";
}

export interface DatabasePayloadDisplay {
  sql: string | null;
  json: string;
  clipboard: string;
}

export function databasePayloadDisplay(
  payload: McpDatabaseToolPayload,
  view: DatabasePayloadView,
): DatabasePayloadDisplay {
  const value =
    view === "request" ? payload.request_payload : payload.response_payload;
  if (!value) {
    return {
      sql: null,
      json: "",
      clipboard: "",
    };
  }

  const sql =
    view === "request" && typeof value.sql === "string"
      ? value.sql
      : null;
  const jsonValue =
    sql === null
      ? value
      : Object.fromEntries(
          Object.entries(value).filter(([key]) => key !== "sql"),
        );
  const json = JSON.stringify(jsonValue, null, 2);
  const clipboard = sql
    ? `${sql}\n\n${json}`
    : json;

  return { sql, json, clipboard };
}
