import assert from "node:assert/strict";
import test from "node:test";

import {
  commitWorkspaceDeploySync,
  previewWorkspaceDeploySync,
} from "./runtime-api";

test("workspace deploy preview and commit use fixed POST endpoints", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; method: string; body?: string }> = [];
  globalThis.fetch = async (input, init) => {
    requests.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? init.body : undefined,
    });
    return new Response(
      JSON.stringify({
        valid: true,
        source_root: "/workspace/deploy/context-router",
        digest: "a".repeat(64),
        profiles: [],
        total: { additions: 0, updates: 0, deletions: 0 },
        synchronized: requests.length === 2,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };

  try {
    await previewWorkspaceDeploySync("workspace-1");
    await commitWorkspaceDeploySync("workspace-1", "a".repeat(64));
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requests, [
    {
      url: "http://127.0.0.1:49173/api/workspaces/workspace-1/runtime-config/sync-preview",
      method: "POST",
      body: undefined,
    },
    {
      url: "http://127.0.0.1:49173/api/workspaces/workspace-1/runtime-config/sync",
      method: "POST",
      body: JSON.stringify({ expected_digest: "a".repeat(64) }),
    },
  ]);
});
