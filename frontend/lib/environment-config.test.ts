import assert from "node:assert/strict";
import test from "node:test";

import { formatEnvironmentJson } from "./environment-config";

test("formats nested environment JSON for read-only display", () => {
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
