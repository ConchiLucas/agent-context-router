# Workspace Card Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a functional “刷新映射” button to the upper-right corner of each workspace card that refreshes the full workspace and updates that card in place.

**Architecture:** Reuse the existing `POST /api/workspaces/{workspace_id}/refresh` endpoint. Add that exact endpoint to both browser POST allowlists, expose it through the frontend API client, and keep per-card request state in `WorkspaceDashboard`; the returned `WorkspaceSummary` replaces only the matching card. Existing broad browser write restrictions remain unchanged.

**Tech Stack:** Next.js 15, React 19, TypeScript, Node test runner, FastAPI/Starlette, pytest, Docker Compose.

---

### Task 1: Permit only the workspace refresh browser command

**Files:**
- Modify: `frontend/lib/browser-api-policy.test.ts`
- Modify: `frontend/lib/browser-api-policy.ts`
- Modify: `backend/tests/test_browser_read_only.py`
- Modify: `backend/src/context_router/middleware/browser_read_only.py`

- [ ] **Step 1: Add the failing frontend allowlist assertions**

Add these assertions to the existing diagnostic POST test and rejection test:

```ts
assert.equal(
  isBrowserApiRequestAllowed(
    "/api/workspaces/workspace-1/refresh",
    "POST",
  ),
  true,
);
assert.equal(
  isBrowserApiRequestAllowed(
    "/api/workspaces/workspace-1/refresh/extra",
    "POST",
  ),
  false,
);
```

- [ ] **Step 2: Run the frontend policy test and verify RED**

Run:

```bash
docker compose exec frontend npm test -- lib/browser-api-policy.test.ts
```

Expected: FAIL because the exact refresh POST currently returns `false`.

- [ ] **Step 3: Add the exact frontend allowlist pattern**

Add this pattern to `SAFE_BROWSER_POST_PATHS`:

```ts
/^\/api\/workspaces\/[^/]+\/refresh$/,
```

- [ ] **Step 4: Run the frontend policy test and verify GREEN**

Run the Step 2 command again. Expected: all browser policy tests PASS.

- [ ] **Step 5: Add the failing backend middleware route and assertions**

Add a test route inside `_app()`:

```python
@app.post("/api/workspaces/workspace-1/refresh")
def refresh_workspace() -> dict[str, bool]:
    return {"refreshed": True}
```

Then assert the browser request succeeds in `test_browser_origin_can_read_and_run_allowlisted_diagnostics`:

```python
assert (
    client.post(
        "/api/workspaces/workspace-1/refresh",
        headers=headers,
    ).status_code
    == 200
)
```

Also add a boundary assertion to the configuration rejection test:

```python
refresh_extra_response = client.post(
    "/api/workspaces/workspace-1/refresh/extra",
    headers=headers,
)
assert refresh_extra_response.status_code == 405
```

- [ ] **Step 6: Run the backend middleware test and verify RED**

Run:

```bash
docker compose exec backend uv run --extra dev pytest -q tests/test_browser_read_only.py
```

Expected: FAIL because the exact refresh request receives HTTP 405.

- [ ] **Step 7: Add the exact backend allowlist pattern**

Add this compiled pattern to `_safe_browser_post_patterns`:

```python
re.compile(rf"^{prefix}/workspaces/[^/]+/refresh$"),
```

- [ ] **Step 8: Run the backend middleware test and verify GREEN**

Restart the modified backend and rerun the focused test:

```bash
docker compose restart backend
docker compose exec backend uv run --extra dev pytest -q tests/test_browser_read_only.py
```

Expected: all middleware tests PASS.

### Task 2: Add the typed frontend refresh request

**Files:**
- Create: `frontend/lib/api.test.ts`
- Modify: `frontend/lib/api.ts`

- [ ] **Step 1: Write a failing API contract test**

Create `frontend/lib/api.test.ts` with a fetch stub that verifies the path and method:

```ts
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
```

- [ ] **Step 2: Run the API test and verify RED**

Run:

```bash
docker compose exec frontend npm test -- lib/api.test.ts
```

Expected: FAIL because `refreshWorkspace` is not exported.

- [ ] **Step 3: Implement the minimal typed API method**

Add after `getWorkspace` in `frontend/lib/api.ts`:

```ts
export function refreshWorkspace(
  workspaceId: string,
): Promise<WorkspaceSummary> {
  return request<WorkspaceSummary>(
    `/api/workspaces/${workspaceId}/refresh`,
    { method: "POST" },
  );
}
```

- [ ] **Step 4: Run the API test and verify GREEN**

Run the Step 2 command again. Expected: the API contract test PASSes.

### Task 3: Add per-card refresh interaction and styling

**Files:**
- Create: `frontend/lib/workspace-dashboard.test.ts`
- Create: `frontend/lib/workspace-dashboard.ts`
- Modify: `frontend/components/workspace-dashboard.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Write the failing card replacement test**

Create `frontend/lib/workspace-dashboard.test.ts`:

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { replaceWorkspaceSummary } from "./workspace-dashboard";
import type { WorkspaceSummary } from "./types";

test("replaces only the refreshed workspace summary", () => {
  const first = { id: "first", name: "First", error_project_count: 3 } as WorkspaceSummary;
  const second = { id: "second", name: "Second", error_project_count: 1 } as WorkspaceSummary;
  const refreshed = { ...first, error_project_count: 0 };

  assert.deepEqual(
    replaceWorkspaceSummary([first, second], refreshed),
    [refreshed, second],
  );
});
```

- [ ] **Step 2: Run the helper test and verify RED**

Run:

```bash
docker compose exec frontend npm test -- lib/workspace-dashboard.test.ts
```

Expected: FAIL because `workspace-dashboard.ts` does not exist.

- [ ] **Step 3: Implement the minimal replacement helper**

Create `frontend/lib/workspace-dashboard.ts`:

```ts
import type { WorkspaceSummary } from "./types";

export function replaceWorkspaceSummary(
  workspaces: readonly WorkspaceSummary[],
  refreshed: WorkspaceSummary,
): WorkspaceSummary[] {
  return workspaces.map((workspace) =>
    workspace.id === refreshed.id ? refreshed : workspace,
  );
}
```

- [ ] **Step 4: Run the helper test and verify GREEN**

Run the Step 2 command again. Expected: the helper test PASSes.

- [ ] **Step 5: Wire per-card state and the click handler**

Import `getWorkspace`, `refreshWorkspace`, and the Workspace dashboard helpers. Track pending IDs in a `Set<string>` and errors in a `Record<string, string>` so concurrent cards remain independent. Use `runWorkspaceRefresh` to recover the latest Workspace summary after a refresh validation error:

```tsx
const handleRefreshWorkspace = useCallback(async (workspaceId: string) => {
  setRefreshingWorkspaceIds((current) =>
    startWorkspaceRefresh(current, workspaceId),
  );
  setRefreshErrors((current) =>
    clearWorkspaceRefreshError(current, workspaceId),
  );
  const result = await runWorkspaceRefresh(
    workspaceId,
    refreshWorkspace,
    getWorkspace,
  );
  const refreshed = result.summary;
  if (refreshed) {
    setWorkspaces((current) =>
      replaceWorkspaceSummary(current, refreshed),
    );
  }
  setRefreshErrors((current) =>
    result.error
      ? setWorkspaceRefreshError(current, workspaceId, result.error)
      : clearWorkspaceRefreshError(current, workspaceId),
  );
  setRefreshingWorkspaceIds((current) =>
    finishWorkspaceRefresh(current, workspaceId),
  );
}, []);
```

Add the button as the second child of the card header:

```tsx
<button
  type="button"
  className="secondary-button workspace-refresh-button"
  disabled={isRefreshing}
  aria-busy={isRefreshing}
  aria-label={
    isRefreshing
      ? `正在刷新 ${workspace.name} 的映射`
      : `刷新 ${workspace.name} 的映射`
  }
  onClick={() => void handleRefreshWorkspace(workspace.id)}
>
  {isRefreshing ? "刷新中…" : "刷新映射"}
</button>
```

- [ ] **Step 6: Add focused card-header styling**

Add:

```css
.workspace-refresh-button {
  flex: 0 0 auto;
  white-space: nowrap;
}
```

The existing `workspace-card > header` flex layout supplies the upper-right placement and preserves the single-column responsive card layout.

- [ ] **Step 7: Run all frontend unit tests**

Run:

```bash
docker compose exec frontend npm test
```

Expected: all frontend tests PASS.

### Task 4: Update repository contracts and verify the complete feature

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/DEVELOPMENT_OUTLINE.md`
- Modify: `docs/STARTUP_GUIDE.md`
- Modify: `docs/DATABASE_INFO.md`
- Modify: `docs/BUSINESS_FEATURES.md`
- Modify: `docs/FRONTEND_BACKEND_FLOW.md`

- [ ] **Step 1: Update the browser capability documentation**

Change references to “four safe POST types” to five and list Workspace refresh alongside connection test, password reveal, MCP integration test, and prepare preview. Clarify that refresh only rebuilds Workspace document caches and derived search indexes; configuration writes remain unavailable from the browser.

- [ ] **Step 2: Run focused backend and frontend verification**

Run:

```bash
docker compose restart backend
docker compose exec backend uv run --extra dev pytest -q tests/test_browser_read_only.py tests/test_workspace_management_api.py
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

Expected: all tests, lint, and build PASS with no warnings.

- [ ] **Step 3: Verify the live browser flow**

Open `http://127.0.0.1:49174`, verify the button is in the workspace card upper-right, click it once, and confirm:

1. the label changes to “刷新中…” while the request is pending;
2. the card remains on the workspace list;
3. the “异常” count updates from the returned summary;
4. the button becomes enabled again;
5. the browser console and page show no request-policy error.

- [ ] **Step 4: Inspect the final diff and commit**

Run:

```bash
git diff --check
git status --short
git add AGENTS.md docs backend frontend
git commit -m "feat: refresh workspace from dashboard card"
```

Expected: only the planned implementation, tests, and documentation are committed.
