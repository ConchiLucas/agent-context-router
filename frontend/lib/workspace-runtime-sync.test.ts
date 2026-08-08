import assert from "node:assert/strict";
import test from "node:test";

import { isBrowserApiRequestAllowed } from "./browser-api-policy";

test("workspace shared file overwrite actions are explicitly allowed", () => {
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/shared-files/restore",
      "POST",
    ),
    true,
  );
  assert.equal(
    isBrowserApiRequestAllowed(
      "/api/workspaces/workspace-1/shared-files/publish",
      "POST",
    ),
    true,
  );
});
