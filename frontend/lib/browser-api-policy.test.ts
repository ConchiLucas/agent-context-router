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
      "/api/workspaces/workspace-1/containers/bulk-action",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/host-runtime/actions",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/relation-records/search",
      "POST",
    ),
    true,
  );
  for (const mode of ["fast", "full"]) {
    assert.equal(
      isBrowserApiRequestAllowed(
        `/api/projects/project-1/runtime-config/${mode}/execute`,
        "POST",
      ),
      true,
    );
  }
  assert.equal(isBrowserApiRequestAllowed("/api/system-guides", "POST"), false);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/import", "POST"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/environments", "POST"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/environments/local", "PUT"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/environments/address-1", "DELETE"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/interfaces/api-1/execute", "POST"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/services/service-1", "PUT"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/interfaces/api-1", "DELETE"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/interface-forwarding/interfaces/api-1/semantics", "PUT"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/value-mappings", "POST"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/value-mappings/mapping-1", "PUT"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/value-mappings/mapping-1", "DELETE"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/value-mappings/mapping-1/preview", "POST"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/shared-config/ai/refresh", "POST"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/shared-config/ai/default", "PUT"), true);
  assert.equal(isBrowserApiRequestAllowed("/api/value-mappings/mapping-1/extra", "POST"), false);
  assert.equal(
    isBrowserApiRequestAllowed("/api/system-guides/guide-1/content", "PUT"),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/mcp-environment-defaults/read_middleware_context",
      "PUT",
    ),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed("/api/system-guides/guide-1", "PUT"),
    false,
  );
  assert.equal(
    isBrowserApiRequestAllowed("/api/system-guides/guide-1", "DELETE"),
    false,
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
      "/api/projects/project-1/runtime-config/turbo/execute",
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
      "/api/workspaces/workspace-1/runtime-config/sync",
      "POST",
    ),
    false,
  );
});
