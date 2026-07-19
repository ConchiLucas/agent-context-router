import assert from "node:assert/strict";
import test from "node:test";

import { parseMarkdown } from "./markdown";

test("parses document index table and hides front matter", () => {
  const blocks = parseMarkdown(`---
doc_id: example
---

# 示例

| 功能说明 | 相对路径 |
| --- | --- |
| 后端说明 | \`./docs/backend.md\` |
`);

  assert.equal(blocks[0].type, "heading");
  assert.equal(blocks[1].type, "table");
  if (blocks[1].type === "table") {
    assert.deepEqual(blocks[1].headers, ["功能说明", "相对路径"]);
    assert.deepEqual(blocks[1].rows, [["后端说明", "`./docs/backend.md`"]]);
  }
});

