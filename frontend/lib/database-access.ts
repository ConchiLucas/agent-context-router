import type {
  ContextDatabaseCallHistoryItem,
  DataSourceEngineCapability,
} from "@/lib/types";
import type { TaskReadRow } from "@/lib/task-history";

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

export function supportsConnectionTest(
  capability: DataSourceEngineCapability | undefined,
): boolean {
  return Boolean(
    capability &&
      (capability.discoverable || capability.searchable || capability.queryable),
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
