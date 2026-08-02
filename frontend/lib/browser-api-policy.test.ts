import assert from "node:assert/strict";
import test from "node:test";

import { isBrowserApiRequestAllowed } from "./browser-api-policy";

test("allows reads and the explicit safe browser POST allowlist", () => {
  assert.equal(isBrowserApiRequestAllowed("/api/workspaces"), true);
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/data-sources/source-1/reveal-password",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/data-sources/source-1/test",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed("/api/mcp/integration/tests", "POST"),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/prepare-preview?environment=test",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/refresh",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/runtime-config/sync-preview",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/runtime-config/sync",
      "POST",
    ),
    true,
  );
});

test("rejects browser configuration and execution commands", () => {
  assert.equal(isBrowserApiRequestAllowed("/api/workspaces", "POST"), false);
  assert.equal(
    isBrowserApiRequestAllowed("/api/workspaces/workspace-1", "PUT"),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/database-environment",
      "PATCH",
    ),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/data-sources/source-1/databases/sync",
      "POST",
    ),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/projects/project-1/runtime-config/fast/execute",
      "POST",
    ),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/refresh/extra",
      "POST",
    ),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/runtime-config/sync/extra",
      "POST",
    ),
    false,
  );
});
