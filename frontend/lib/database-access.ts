import type {
  ContextDatabaseCallHistoryItem,
  DataSourceEngineCapability,
} from "@/lib/types";
import type { TaskReadRow } from "@/lib/task-history";

export interface ClickHouseConnectionFields {
  secure: boolean;
  verify: boolean;
  bootstrapDatabase: string;
  connectTimeoutSeconds: string;
  sendReceiveTimeoutSeconds: string;
}

export interface DatabaseAliasCandidate {
  databaseId: string;
  value: string;
  required: boolean;
}

export type TaskContextTimelineItem =
  | {
      kind: "read";
      eventNumber: number;
      createdAt: string;
      row: TaskReadRow;
    }
  | {
      kind: "database";
      eventNumber: number;
      createdAt: string;
      call: ContextDatabaseCallHistoryItem;
    };

const MCP_ALIAS_PATTERN = /^[a-z][a-z0-9_-]{0,63}$/;

function booleanConfigValue(value: unknown, fallback: boolean): boolean {
  if (typeof value === "boolean") return value;
  if (value === "true") return true;
  if (value === "false") return false;
  return fallback;
}

function stringConfigValue(value: unknown, fallback: string): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return fallback;
}

export function clickHouseFieldsFromConfig(
  config: Record<string, unknown>,
): ClickHouseConnectionFields {
  return {
    secure: booleanConfigValue(config.secure, false),
    verify: booleanConfigValue(config.verify, true),
    bootstrapDatabase: stringConfigValue(config.bootstrap_database, "default"),
    connectTimeoutSeconds: stringConfigValue(config.connect_timeout_seconds, "8"),
    sendReceiveTimeoutSeconds: stringConfigValue(
      config.send_receive_timeout_seconds,
      "15",
    ),
  };
}

export function clickHouseConfigFromFields(
  fields: ClickHouseConnectionFields,
): Record<string, string | number | boolean> {
  return {
    secure: fields.secure,
    verify: fields.verify,
    bootstrap_database: fields.bootstrapDatabase.trim() || "default",
    connect_timeout_seconds: Number(fields.connectTimeoutSeconds || 8),
    send_receive_timeout_seconds: Number(fields.sendReceiveTimeoutSeconds || 15),
  };
}

export function supportsConnectionTest(
  capability: DataSourceEngineCapability | undefined,
): boolean {
  return Boolean(
    capability &&
      (capability.discoverable || capability.searchable || capability.queryable),
  );
}

export function validateDatabaseAliases(
  candidates: DatabaseAliasCandidate[],
): Record<string, string> {
  const errors: Record<string, string> = {};
  const databaseIdsByAlias = new Map<string, string[]>();

  candidates.forEach((candidate) => {
    const value = candidate.value.trim();
    if (!value) {
      if (candidate.required) errors[candidate.databaseId] = "MCP 别名不能为空";
      return;
    }
    if (!MCP_ALIAS_PATTERN.test(value)) {
      errors[candidate.databaseId] =
        "须以小写字母开头，只能包含小写字母、数字、_ 或 -，最长 64 个字符";
      return;
    }
    databaseIdsByAlias.set(value, [
      ...(databaseIdsByAlias.get(value) ?? []),
      candidate.databaseId,
    ]);
  });

  databaseIdsByAlias.forEach((databaseIds) => {
    if (databaseIds.length < 2) return;
    databaseIds.forEach((databaseId) => {
      errors[databaseId] = "同一项目内的 MCP 别名不能重复";
    });
  });
  return errors;
}

export function buildSelectedDatabaseAliases(
  selectedDatabaseIds: Iterable<string>,
  drafts: Record<string, string>,
): Record<string, string> {
  return Object.fromEntries(
    Array.from(selectedDatabaseIds)
      .map((databaseId) => [databaseId, drafts[databaseId]?.trim() ?? ""] as const)
      .filter(([, alias]) => alias.length > 0),
  );
}

export function buildTaskContextTimeline(
  readRows: TaskReadRow[],
  databaseCalls: ContextDatabaseCallHistoryItem[],
): TaskContextTimelineItem[] {
  const items = [
    ...readRows.map((row, index) => ({
      kind: "read" as const,
      createdAt: row.createdAt,
      order: index,
      row,
    })),
    ...databaseCalls.map((call, index) => ({
      kind: "database" as const,
      createdAt: call.created_at,
      order: readRows.length + index,
      call,
    })),
  ];

  return items
    .sort((left, right) => {
      const timeDifference = Date.parse(left.createdAt) - Date.parse(right.createdAt);
      return timeDifference || left.order - right.order;
    })
    .map((item, index) => ({ ...item, eventNumber: index + 1 }));
}
