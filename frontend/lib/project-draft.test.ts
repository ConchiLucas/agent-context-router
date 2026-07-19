import assert from "node:assert/strict";
import test from "node:test";

import { projectDraftToPayload } from "./project-draft";

test("projectDraftToPayload trims fields and omits blank optional values", () => {
  assert.deepEqual(
    projectDraftToPayload({
      name: " Context Router ",
      slug: " context-router ",
      rootPath: " /workspace/context-router ",
      description: " MCP context docs ",
      parentSlug: " ",
    }),
    {
      name: "Context Router",
      slug: "context-router",
      root_path: "/workspace/context-router",
      description: "MCP context docs",
      parent_slug: null,
    }
  );
});

test("projectDraftToPayload rejects missing required fields", () => {
  assert.throws(
    () =>
      projectDraftToPayload({
        name: "",
        slug: "",
        rootPath: "",
        description: "",
        parentSlug: "",
      }),
    /Name and slug are required/
  );
});
