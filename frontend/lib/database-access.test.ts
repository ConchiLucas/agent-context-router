import assert from "node:assert/strict";
import test from "node:test";

import {
  buildSelectedDatabaseAliases,
  buildTaskContextTimeline,
  clickHouseConfigFromFields,
  clickHouseFieldsFromConfig,
  supportsConnectionTest,
  validateDatabaseAliases,
} from "./database-access";

test("builds one atomic alias payload for selected databases", () => {
  assert.deepEqual(
    buildSelectedDatabaseAliases(new Set(["database-a", "database-b"]), {
      "database-a": " analytics ",
      "database-b": "",
      "database-c": "not-selected",
    }),
    { "database-a": "analytics" },
  );
});

test("round-trips ClickHouse TLS, bootstrap database, and timeout fields", () => {
  const fields = clickHouseFieldsFromConfig({
    secure: true,
    verify: false,
    bootstrap_database: "analytics",
    connect_timeout_seconds: 12,
    send_receive_timeout_seconds: 45,
  });

  assert.deepEqual(fields, {
    secure: true,
    verify: false,
    bootstrapDatabase: "analytics",
    connectTimeoutSeconds: "12",
    sendReceiveTimeoutSeconds: "45",
  });
  assert.deepEqual(clickHouseConfigFromFields(fields), {
    secure: true,
    verify: false,
    bootstrap_database: "analytics",
    connect_timeout_seconds: 12,
    send_receive_timeout_seconds: 45,
  });
});

test("uses backend capabilities to decide whether connection testing is available", () => {
  assert.equal(
    supportsConnectionTest({
      engine: "clickhouse",
      configurable: true,
      discoverable: true,
      searchable: true,
      queryable: true,
    }),
    true,
  );
  assert.equal(
    supportsConnectionTest({
      engine: "oracle",
      configurable: true,
      discoverable: false,
      searchable: false,
      queryable: false,
    }),
    false,
  );
});

test("validates MCP alias format, required values, and project-local duplicates", () => {
  assert.deepEqual(
    validateDatabaseAliases([
      { databaseId: "existing-empty", value: "", required: true },
      { databaseId: "new-empty", value: "", required: false },
      { databaseId: "invalid", value: "Bad Alias", required: false },
      { databaseId: "duplicate-a", value: "analytics", required: true },
      { databaseId: "duplicate-b", value: "analytics", required: false },
    ]),
    {
      "existing-empty": "MCP 别名不能为空",
      invalid:
        "须以小写字母开头，只能包含小写字母、数字、_ 或 -，最长 64 个字符",
      "duplicate-a": "同一项目内的 MCP 别名不能重复",
      "duplicate-b": "同一项目内的 MCP 别名不能重复",
    },
  );
});

test("merges document and database calls into a chronological timeline", () => {
  const timeline = buildTaskContextTimeline(
    [
      {
        callNumber: 1,
        readCallId: 10,
        createdAt: "2026-07-23T10:02:00Z",
        steps: [],
      },
    ],
    [
      {
        database_call_id: 20,
        operation: "search_objects",
        database: "analytics",
        engine: "clickhouse",
        status: "ok",
        created_at: "2026-07-23T10:01:00Z",
      },
    ],
  );

  assert.deepEqual(
    timeline.map((item) => ({ kind: item.kind, eventNumber: item.eventNumber })),
    [
      { kind: "database", eventNumber: 1 },
      { kind: "read", eventNumber: 2 },
    ],
  );
});
