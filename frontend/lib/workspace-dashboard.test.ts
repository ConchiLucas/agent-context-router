import assert from "node:assert/strict";
import test from "node:test";

import {
  clearWorkspaceRefreshError,
  finishWorkspaceRefresh,
  replaceWorkspaceSummary,
  runWorkspaceRefresh,
  setWorkspaceRefreshError,
  startWorkspaceRefresh,
} from "./workspace-dashboard";
import type { WorkspaceSummary } from "./types";

test("replaces only the refreshed workspace summary", () => {
  const first = {
    id: "first",
    name: "First",
    error_project_count: 3,
  } as WorkspaceSummary;
  const second = {
    id: "second",
    name: "Second",
    error_project_count: 1,
  } as WorkspaceSummary;
  const refreshed = { ...first, error_project_count: 0 };

  assert.deepEqual(
    replaceWorkspaceSummary([first, second], refreshed),
    [refreshed, second],
  );
});

test("tracks concurrent workspace refreshes independently", () => {
  const firstPending = startWorkspaceRefresh(new Set<string>(), "first");
  const bothPending = startWorkspaceRefresh(firstPending, "second");
  const secondPending = finishWorkspaceRefresh(bothPending, "first");

  assert.deepEqual([...firstPending], ["first"]);
  assert.deepEqual([...bothPending], ["first", "second"]);
  assert.deepEqual([...secondPending], ["second"]);
});

test("returns the latest workspace summary when refresh validation fails", async () => {
  const latest = {
    id: "first",
    name: "First",
    error_project_count: 1,
  } as WorkspaceSummary;

  const result = await runWorkspaceRefresh(
    "first",
    async () => {
      throw new Error("工作空间刷新失败");
    },
    async () => latest,
  );

  assert.deepEqual(result, {
    summary: latest,
    error: "工作空间刷新失败",
  });
});

test("clears only the completing workspace refresh error", () => {
  const firstFailed = setWorkspaceRefreshError(
    {},
    "first",
    "First failed",
  );
  const bothFailed = setWorkspaceRefreshError(
    firstFailed,
    "second",
    "Second failed",
  );
  const firstStillFailed = clearWorkspaceRefreshError(
    bothFailed,
    "second",
  );

  assert.deepEqual(firstStillFailed, { first: "First failed" });
});
