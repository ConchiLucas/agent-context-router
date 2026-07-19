# Recursive Document Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore the original connected document-tree presentation while preserving arbitrary depth, orphan documents, and broken-link health information.

**Architecture:** Build a deterministic, cycle-safe hierarchy from synced `DocumentSummary.links` and `graph_depth`, then render it recursively with the original node-card and connector visual language. Keep orphan and broken-link derivation in the existing health helper and render those sections below the connected tree.

**Tech Stack:** TypeScript, React Server Components, Next.js 15, Node test runner, CSS.

---

### Task 1: Build a deterministic recursive document hierarchy

**Files:**
- Modify: `frontend/lib/document-health.ts`
- Modify: `frontend/lib/document-health.test.ts`

- [ ] **Step 1: Write failing hierarchy tests**

Add tests that create `entry -> business -> schema -> table`, a cycle from `table -> business`, and a second direct reference from `entry -> schema`. Assert:

```typescript
const hierarchy = buildDocumentHierarchy(documents, "orders");
assert.equal(hierarchy?.document.id, "entry");
assert.equal(hierarchy?.children[0].document.id, "business");
assert.equal(hierarchy?.children[0].children[0].document.id, "schema");
assert.equal(hierarchy?.children[0].children[0].children[0].document.id, "table");
assert.equal(hierarchy?.children[0].children[0].children[0].children[0].isReference, true);
assert.equal(hierarchy?.children[1].document.id, "schema");
assert.equal(hierarchy?.children[1].isReference, true);
```

The fixtures must use real `DocumentSummary` fields and links sorted by `sort_order`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
docker compose exec frontend npm test
```

Expected: FAIL because `buildDocumentHierarchy` is not exported.

- [ ] **Step 3: Implement the hierarchy builder**

Add:

```typescript
export type DocumentHierarchyNode = {
  document: DocumentSummary;
  edgeLabel: string | null;
  isReference: boolean;
  children: DocumentHierarchyNode[];
};

export function buildDocumentHierarchy(
  documents: DocumentSummary[],
  project?: string,
): DocumentHierarchyNode | null;
```

Implementation rules:

- Choose an active, reachable `agent_index` with `graph_depth === 1`, preferring `project_slug === project`.
- Follow only non-broken links whose targets exist, are active, and are reachable.
- Sort outgoing links by `sort_order`, then `target_path`.
- Expand a target only when its depth is exactly parent depth + 1 and it has not been globally expanded.
- Render cycle, cross-level, and duplicate targets as `isReference=true` nodes with no children.
- Preserve the Markdown link label as `edgeLabel`.

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```bash
docker compose exec frontend npm test
```

Expected: all frontend unit tests PASS.

### Task 2: Restore the connected hierarchy presentation

**Files:**
- Modify: `frontend/components/document-graph.tsx`
- Modify: `frontend/app/globals.css`

- [ ] **Step 1: Replace Level sections with a recursive tree renderer**

Use `buildDocumentHierarchy(documents, project)` and render:

```tsx
<div className="document-hierarchy-scroll">
  <div className="document-hierarchy-tree">
    <DocumentTreeBranch node={hierarchy} detailHref={detailHref} />
  </div>
</div>
```

`DocumentTreeBranch` must render the current original-style `DocumentGraphNode`, a horizontal arrow connector, and a vertical child column. Root, branch, leaf, and reference nodes receive distinct existing-style classes. The card continues to show preview, title, source path, document ID, and direct child count.

- [ ] **Step 2: Keep health sections below the main tree**

Continue using `groupDocumentsByDepth(documents)` only for `orphans` and `brokenLinks`. Render orphan cards and broken-link rows after the connected hierarchy, without Level 1/2/3 containers.

- [ ] **Step 3: Restore original visual language with arbitrary-depth overflow**

CSS requirements:

```css
.document-hierarchy-scroll { overflow-x: auto; }
.document-hierarchy-branch { display: flex; align-items: center; }
.document-hierarchy-children { display: grid; }
```

Use pseudo-elements for the vertical spine and per-child horizontal connector. Preserve original purple root/branch styling and arrow connector. On screens below 620px, hide connector lines and stack branch children vertically so no node is clipped.

- [ ] **Step 4: Run full frontend verification**

Run:

```bash
docker compose exec frontend npm test
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

Expected: tests, lint, and production build all exit 0.

- [ ] **Step 5: Browser acceptance**

Open the mapped Documents Graph and verify:

```text
AGENTS.md root -> Business workflow -> Database schema -> fourth-level fixture
```

Each level must be connected left-to-right. Orphan maintenance note and the missing-link row remain below the main tree. Preview links must still open the existing document detail.

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/document-health.ts frontend/lib/document-health.test.ts frontend/components/document-graph.tsx frontend/app/globals.css
git commit -m "fix: restore connected document hierarchy"
```
