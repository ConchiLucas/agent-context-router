import assert from "node:assert/strict";
import test from "node:test";

import {
  keywordHistoryStorageKey,
  lastSearchStorageKey,
  parseLastSearch,
  parseKeywordHistory,
  rememberKeyword,
} from "./relation-record-keyword-history";

test("last search is isolated by workspace and environment", () => {
  assert.notEqual(
    lastSearchStorageKey({ workspaceId: "workspace-1", environment: "local" }),
    lastSearchStorageKey({ workspaceId: "workspace-1", environment: "test" }),
  );
  assert.notEqual(
    lastSearchStorageKey({ workspaceId: "workspace-1", environment: "local" }),
    lastSearchStorageKey({ workspaceId: "workspace-2", environment: "local" }),
  );
});

test("last search parser keeps only a complete valid selection", () => {
  assert.deepEqual(parseLastSearch(JSON.stringify({
    databaseKey: " c12_mtp_db ",
    schemaName: "uat_mtp",
    tableName: "cs_dsly_line_route",
    keyword: " 1 ",
  })), {
    databaseKey: "c12_mtp_db",
    schemaName: "uat_mtp",
    tableName: "cs_dsly_line_route",
    keyword: "1",
  });
  assert.equal(parseLastSearch(JSON.stringify({ databaseKey: "db" })), null);
  assert.equal(parseLastSearch("not-json"), null);
});

test("keyword history is isolated by workspace environment and table", () => {
  const base = {
    workspaceId: "workspace-1",
    environment: "test",
    databaseKey: "c12_mtp_db",
    schemaName: "uat_mtp",
    tableName: "cs_bt_departure_plan",
  };

  assert.notEqual(
    keywordHistoryStorageKey(base),
    keywordHistoryStorageKey({ ...base, tableName: "cs_dsly_line_route" }),
  );
  assert.notEqual(
    keywordHistoryStorageKey(base),
    keywordHistoryStorageKey({ ...base, environment: "uat" }),
  );
});

test("rememberKeyword moves the latest exact value to the front and bounds history", () => {
  assert.deepEqual(rememberKeyword(["A", "B", "C"], " B ", 3), ["B", "A", "C"]);
  assert.deepEqual(rememberKeyword(["A", "B", "C"], "D", 3), ["D", "A", "B"]);
});

test("parseKeywordHistory tolerates invalid storage and removes unusable values", () => {
  assert.deepEqual(parseKeywordHistory("not-json"), []);
  assert.deepEqual(parseKeywordHistory(JSON.stringify([" A ", "", 1, "A", "B"])), ["A", "B"]);
});
