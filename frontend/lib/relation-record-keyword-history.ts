const STORAGE_PREFIX = "agent-context:relation-record-keywords:v1";
const LAST_SEARCH_STORAGE_PREFIX = "agent-context:relation-record-last-search:v1";
const DEFAULT_HISTORY_LIMIT = 12;

export type RelationRecordKeywordScope = {
  workspaceId: string;
  environment: string;
  databaseKey: string;
  schemaName: string;
  tableName: string;
};

export type RelationRecordLastSearch = {
  databaseKey: string;
  schemaName: string;
  tableName: string;
  keyword: string;
};

export function lastSearchStorageKey(scope: {
  workspaceId: string;
  environment: string;
}): string {
  return `${LAST_SEARCH_STORAGE_PREFIX}:${encodeURIComponent(scope.workspaceId)}:${encodeURIComponent(scope.environment)}`;
}

export function parseLastSearch(raw: string | null): RelationRecordLastSearch | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const value = parsed as Record<string, unknown>;
    const fields = ["databaseKey", "schemaName", "tableName", "keyword"] as const;
    if (fields.some((field) => typeof value[field] !== "string" || !(value[field] as string).trim())) {
      return null;
    }
    return {
      databaseKey: (value.databaseKey as string).trim(),
      schemaName: (value.schemaName as string).trim(),
      tableName: (value.tableName as string).trim(),
      keyword: (value.keyword as string).trim(),
    };
  } catch {
    return null;
  }
}

export function keywordHistoryStorageKey(scope: RelationRecordKeywordScope): string {
  const parts = [
    scope.workspaceId,
    scope.environment,
    scope.databaseKey,
    scope.schemaName,
    scope.tableName,
  ];
  return `${STORAGE_PREFIX}:${parts.map(encodeURIComponent).join(":")}`;
}

export function parseKeywordHistory(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is string => typeof item === "string")
      .map((item) => item.trim())
      .filter((item, index, items) => item.length > 0 && items.indexOf(item) === index)
      .slice(0, DEFAULT_HISTORY_LIMIT);
  } catch {
    return [];
  }
}

export function rememberKeyword(
  history: string[],
  keyword: string,
  limit = DEFAULT_HISTORY_LIMIT,
): string[] {
  const normalized = keyword.trim();
  if (!normalized) return history.slice(0, limit);
  return [normalized, ...history.filter((item) => item !== normalized)].slice(0, limit);
}
