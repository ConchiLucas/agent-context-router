import assert from "node:assert/strict";
import test from "node:test";

import {
  canCommitWorkspaceDeploySync,
  workspaceDeployChangeLabel,
} from "../components/workspace-runtime-sync";
import type { WorkspaceDeploySyncPreview } from "./runtime-api";

const preview: WorkspaceDeploySyncPreview = {
  valid: true,
  source_root: "/workspace/deploy/context-router",
  digest: "a".repeat(64),
  profiles: [],
  total: { additions: 3, updates: 2, deletions: 1 },
  synchronized: false,
};

test("workspace runtime sync enables commit only for an idle valid preview", () => {
  assert.equal(canCommitWorkspaceDeploySync(preview, false), true);
  assert.equal(canCommitWorkspaceDeploySync(preview, true), false);
  assert.equal(canCommitWorkspaceDeploySync(null, false), false);
  assert.equal(
    canCommitWorkspaceDeploySync({ ...preview, valid: false }, false),
    false,
  );
});

test("workspace runtime sync summarizes additions updates and deletions", () => {
  assert.equal(
    workspaceDeployChangeLabel(preview.total),
    "新增 3 · 更新 2 · 删除 1",
  );
});
