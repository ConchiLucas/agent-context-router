import assert from "node:assert/strict";
import test from "node:test";

import {
  projectDirectoryName,
  suggestProjectDocumentRelativePath,
} from "./project-paths";

test("extracts the final project directory from a workspace-relative path", () => {
  assert.equal(projectDirectoryName("backend/crz-wms-pda"), "crz-wms-pda");
  assert.equal(projectDirectoryName("services/order/"), "order");
});

test("does not invent a document directory for an empty or root project path", () => {
  assert.equal(projectDirectoryName(""), null);
  assert.equal(projectDirectoryName("."), null);
  assert.equal(suggestProjectDocumentRelativePath("backend", "."), "");
});

test("suggests the docs hierarchy from project kind rather than source parent", () => {
  assert.equal(
    suggestProjectDocumentRelativePath("frontend", "backend/crz-wms-pda"),
    "docs/frontend/crz-wms-pda/AGENTS.md",
  );
  assert.equal(
    suggestProjectDocumentRelativePath("backend", "backend/c12-mtp"),
    "docs/backend/c12-mtp/AGENTS.md",
  );
});
