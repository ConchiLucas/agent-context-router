import assert from "node:assert/strict";
import test from "node:test";

import { scriptCountText, scriptKindLabel } from "./script-health";

test("scriptKindLabel maps workspace kinds", () => {
  assert.equal(scriptKindLabel("workspace_ai"), "AI");
  assert.equal(scriptKindLabel("workspace_autostart"), "开机");
  assert.equal(scriptKindLabel("other"), "other");
});

test("scriptCountText shows total and autostart counts", () => {
  assert.equal(scriptCountText(7, 1), "7 total / 1 autostart");
});
