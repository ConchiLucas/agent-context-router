import assert from "node:assert/strict";
import test from "node:test";

import {
  buildDocumentChildLayout,
  documentNodeLabel,
  MAX_DOCUMENT_CHILDREN_PER_ROW,
  resolveDocumentPath,
  shouldShowDocumentSubtreeAction,
} from "./document-tree";
import type { DocumentTreeNode } from "./types";

function documentNode(
  id: string,
  children: DocumentTreeNode[] = [],
  overrides: Partial<DocumentTreeNode> = {},
): DocumentTreeNode {
  return {
    id,
    description: id,
    path: `/workspace/${id}.md`,
    relative_path: `./${id}.md`,
    error: null,
    children,
    ...overrides,
  };
}

test("keeps every second-level document in one row", () => {
  const children = Array.from({ length: 10 }, (_, index) => `child-${index}`);
  const layout = buildDocumentChildLayout(children, 1);

  assert.deepEqual(layout.rows, [children]);
  assert.equal(layout.suppressRenderedChildDescendants, false);
});

test("continues recursively when a deeper parent has four children", () => {
  const children = Array.from(
    { length: MAX_DOCUMENT_CHILDREN_PER_ROW },
    (_, index) => `child-${index}`,
  );
  const layout = buildDocumentChildLayout(children, 2);

  assert.deepEqual(layout.rows, [children]);
  assert.equal(layout.suppressRenderedChildDescendants, false);
});

test("wraps deeper siblings four per row and stops their inline descendants", () => {
  const children = Array.from(
    { length: MAX_DOCUMENT_CHILDREN_PER_ROW * 2 + 2 },
    (_, index) => `child-${index}`,
  );
  const layout = buildDocumentChildLayout(children, 2);

  assert.deepEqual(
    layout.rows.map((row) => row.length),
    [4, 4, 2],
  );
  assert.deepEqual(layout.rows.flat(), children);
  assert.equal(layout.suppressRenderedChildDescendants, true);
});

test("applies the same overflow boundary at any deeper level", () => {
  const overflowed = buildDocumentChildLayout(
    Array.from(
      { length: MAX_DOCUMENT_CHILDREN_PER_ROW + 1 },
      (_, index) => index,
    ),
    7,
  );
  const inline = buildDocumentChildLayout(
    Array.from(
      { length: MAX_DOCUMENT_CHILDREN_PER_ROW },
      (_, index) => index,
    ),
    7,
  );

  assert.deepEqual(
    overflowed.rows.map((row) => row.length),
    [4, 1],
  );
  assert.equal(overflowed.suppressRenderedChildDescendants, true);
  assert.deepEqual(
    inline.rows.map((row) => row.length),
    [4],
  );
  assert.equal(inline.suppressRenderedChildDescendants, false);
});

test("shows a subtree action only for a suppressed card with descendants", () => {
  const branch = documentNode("branch", [documentNode("leaf")]);
  const leaf = documentNode("leaf");

  assert.equal(shouldShowDocumentSubtreeAction(branch, true), true);
  assert.equal(shouldShowDocumentSubtreeAction(branch, false), false);
  assert.equal(shouldShowDocumentSubtreeAction(leaf, true), false);
});

test("evaluates overflow independently for sibling branches", () => {
  const deepLeaf = documentNode("deep-leaf");
  const recursiveChild = documentNode("recursive-child", [deepLeaf]);
  const overflowedParent = documentNode(
    "overflowed-parent",
    Array.from(
      { length: MAX_DOCUMENT_CHILDREN_PER_ROW + 1 },
      (_, index) => documentNode(`overflowed-child-${index}`),
    ),
  );
  const recursiveParent = documentNode("recursive-parent", [
    recursiveChild,
    documentNode("sibling"),
  ]);
  const secondLevel = buildDocumentChildLayout(
    [overflowedParent, recursiveParent],
    1,
  );
  const overflowedBranch = buildDocumentChildLayout(
    overflowedParent.children,
    2,
  );
  const recursiveBranch = buildDocumentChildLayout(
    recursiveParent.children,
    2,
  );
  const deeperBranch = buildDocumentChildLayout(
    recursiveChild.children,
    3,
  );

  assert.deepEqual(secondLevel.rows, [[overflowedParent, recursiveParent]]);
  assert.equal(
    overflowedBranch.suppressRenderedChildDescendants,
    true,
  );
  assert.equal(recursiveBranch.suppressRenderedChildDescendants, false);
  assert.deepEqual(deeperBranch.rows, [[deepLeaf]]);
  assert.equal(deeperBranch.suppressRenderedChildDescendants, false);
});

test("resets the local depth when an overflowed card becomes a subtree root", () => {
  const children = Array.from(
    { length: MAX_DOCUMENT_CHILDREN_PER_ROW + 2 },
    (_, index) => documentNode(`child-${index}`),
  );
  const branch = documentNode("branch", children);

  assert.equal(shouldShowDocumentSubtreeAction(branch, true), true);

  const subtreeRootLayout = buildDocumentChildLayout(branch.children, 1);
  assert.deepEqual(subtreeRootLayout.rows, [children]);
  assert.equal(
    subtreeRootLayout.suppressRenderedChildDescendants,
    false,
  );
});

test("resolves the complete breadcrumb path from child indexes", () => {
  const leaf = documentNode("leaf");
  const branch = documentNode("branch", [leaf]);
  const root = documentNode("root", [branch]);

  assert.deepEqual(resolveDocumentPath(root, []), [root]);
  assert.deepEqual(
    resolveDocumentPath(root, [0, 0])?.map((node) => node.id),
    ["root", "branch", "leaf"],
  );
  assert.equal(resolveDocumentPath(root, [1]), null);
});

test("keeps the selected parent chain when a document is referenced twice", () => {
  const firstShared = documentNode("shared");
  const secondShared = documentNode("shared");
  const root = documentNode("root", [
    documentNode("first-parent", [firstShared]),
    documentNode("second-parent", [secondShared]),
  ]);
  const selectedPath = resolveDocumentPath(root, [1, 0]);

  assert.deepEqual(
    selectedPath?.map((node) => node.id),
    ["root", "second-parent", "shared"],
  );
  assert.equal(selectedPath?.at(-1), secondShared);
  assert.notEqual(selectedPath?.at(-1), firstShared);
});

test("distinguishes duplicate references under the same parent", () => {
  const firstShared = documentNode("shared");
  const secondShared = documentNode("shared");
  const root = documentNode("root", [firstShared, secondShared]);

  assert.equal(resolveDocumentPath(root, [0])?.at(-1), firstShared);
  assert.equal(resolveDocumentPath(root, [1])?.at(-1), secondShared);
});

test("uses the existing concise labels in subtree breadcrumbs", () => {
  assert.equal(
    documentNodeLabel(
      documentNode("root", [], {
        relative_path: null,
        path: "/workspace/AGENTS.md",
      }),
    ),
    "项目文档入口",
  );
  assert.equal(
    documentNodeLabel(
      documentNode("subprojects", [], {
        path: "/workspace/panzhihua-dsly-workforce-subprojects-overview.md",
      }),
    ),
    "子项目总览",
  );
});
