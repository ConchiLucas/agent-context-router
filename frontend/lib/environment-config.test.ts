import assert from "node:assert/strict";
import test from "node:test";

import {
  ENVIRONMENT_JSON_TOTAL_MAX_BYTES,
  environmentJsonByteLength,
  formatEnvironmentJson,
  parseEnvironmentJson,
} from "./environment-config";

test("parses arbitrary environment objects without imposing fixed fields", () => {
  const objectResult = parseEnvironmentJson(
    '{"messageQueue":{"endpoint":"internal"},"flags":[true,2]}',
  );

  assert.deepEqual(objectResult, {
    ok: true,
    value: {
      messageQueue: { endpoint: "internal" },
      flags: [true, 2],
    },
  });
});

test("rejects empty, malformed, or non-object top-level JSON", () => {
  assert.deepEqual(parseEnvironmentJson("   "), {
    ok: false,
    error: "JSON 不能为空",
  });
  for (const source of ['["test",null,3]', "false", "null", '"text"']) {
    assert.deepEqual(parseEnvironmentJson(source), {
      ok: false,
      error: "环境 JSON 顶层必须是对象",
    });
  }

  const malformed = parseEnvironmentJson('{"password":"sensitive",}');
  assert.equal(malformed.ok, false);
  if (!malformed.ok) {
    assert.equal(malformed.error.includes("sensitive"), false);
  }
});

test("rejects unsafe integer literals and asks callers to use strings", () => {
  assert.deepEqual(
    parseEnvironmentJson('{"unsafe":9007199254740993}'),
    {
      ok: false,
      error: "JSON 含超出 JavaScript 安全整数范围的数字，请改用字符串",
    },
  );
  assert.deepEqual(parseEnvironmentJson('{"safe":9007199254740991}'), {
    ok: true,
    value: { safe: 9007199254740991 },
  });
});

test("counts the combined UTF-8 size of TEST and UAT drafts", () => {
  assert.equal(environmentJsonByteLength(["{}", "中文"]), 8);
  assert.equal(
    environmentJsonByteLength([
      "a".repeat(ENVIRONMENT_JSON_TOTAL_MAX_BYTES - 2),
      "{}",
    ]),
    ENVIRONMENT_JSON_TOTAL_MAX_BYTES,
  );
  assert.equal(
    environmentJsonByteLength([
      "a".repeat(ENVIRONMENT_JSON_TOTAL_MAX_BYTES - 1),
      "{}",
    ]),
    ENVIRONMENT_JSON_TOTAL_MAX_BYTES + 1,
  );
});

test("formats nested environment JSON for the editor", () => {
  assert.equal(
    formatEnvironmentJson({ nested: { enabled: true } }),
    '{\n  "nested": {\n    "enabled": true\n  }\n}',
  );
});

test("formats top-level middleware first without reordering other keys", () => {
  assert.equal(
    formatEnvironmentJson({
      service: { endpoint: "internal" },
      middleware: { redis: { host: "127.0.0.1" } },
      featureFlags: { enabled: true },
    }),
    '{\n  "middleware": {\n    "redis": {\n      "host": "127.0.0.1"\n    }\n  },\n  "service": {\n    "endpoint": "internal"\n  },\n  "featureFlags": {\n    "enabled": true\n  }\n}',
  );
});
