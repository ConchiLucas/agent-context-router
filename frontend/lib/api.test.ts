import assert from "node:assert/strict";
import test from "node:test";

import { refreshWorkspace } from "./api";

test("refreshWorkspace posts to the workspace refresh endpoint", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  let requestedMethod = "";
  globalThis.fetch = async (input, init) => {
    requestedUrl = String(input);
    requestedMethod = init?.method ?? "GET";
    return new Response(
      JSON.stringify({ id: "workspace-1", name: "Workspace" }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    const result = await refreshWorkspace("workspace-1");
    assert.equal(
      requestedUrl,
      "http://127.0.0.1:49173/api/workspaces/workspace-1/refresh",
    );
    assert.equal(requestedMethod, "POST");
    assert.equal(result.id, "workspace-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
