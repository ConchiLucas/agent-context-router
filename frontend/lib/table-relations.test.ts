import assert from "node:assert/strict";
import test from "node:test";

import {
  cardinalityBadge,
  codeEvidenceExplanation,
  codeEvidenceLabel,
  dbEvidenceExplanation,
  dbEvidenceLabel,
  dimensionsAgree,
  disagreementCount,
  filterTableSummaries,
  groupRelationSites,
  missingSitesNote,
  relationCheckCopy,
  relationVerdicts,
  siteKindExplanation,
  siteKindTitle,
  sortTableSummaries,
  unrelatedTableCount,
  writeKindExplanation,
  writeKindTitle,
  missingWritesNote,
  missingUpdatesNote,
} from "./table-relations";
import type {
  TableRelationCheck,
  TableRelationCodeEvidence,
  TableRelationCodeSite,
  TableRelationDbEvidence,
  TableRelationMeasurement,
  TableRelationTableSummary,
  TableRelationView,
} from "./types";

function relation(overrides: Partial<TableRelationView> = {}): TableRelationView {
  return {
    edge_id: "edge-1",
    relation_id: "cs_dsly_highway_cargo.carrier_order_no",
    references: "cs_dsly_highway_carrier_order.carrier_order_no",
    child: {
      database_key: "c12_mtp_db",
      schema_name: "uat_mtp",
      table_name: "cs_dsly_highway_cargo",
      column_name: "carrier_order_no",
    },
    parent: {
      database_key: "c12_mtp_db",
      schema_name: "uat_mtp",
      table_name: "cs_dsly_highway_carrier_order",
      column_name: "carrier_order_no",
    },
    direction: "inbound",
    code_cardinality: "one_to_many",
    code_evidence: "batch_allowed",
    db_cardinality: "one_to_many",
    db_evidence: "measured",
    cross_database: false,
    ...overrides,
  };
}

function summary(
  overrides: Partial<TableRelationTableSummary> & Pick<TableRelationTableSummary, "table_name">,
): TableRelationTableSummary {
  return {
    database_key: "c12_mtp_db",
    schema_name: "uat_mtp",
    relation_count: 1,
    hidden_count: 0,
    ...overrides,
  };
}

function measurement(
  overrides: Partial<TableRelationMeasurement> = {},
): TableRelationMeasurement {
  return {
    child_key_kind: "numeric",
    parent_key_kind: "numeric",
    child_table_rows: 183,
    child_rows_with_value: 183,
    child_distinct_keys: 49,
    parent_rows_with_value: 48,
    parent_distinct_keys: 48,
    orphan_keys: 27,
    ...overrides,
  };
}

function check(
  key: TableRelationCheck["key"],
  outcome: TableRelationCheck["outcome"],
): TableRelationCheck {
  return { key, outcome, sql: "SELECT 1;" };
}

test("every cardinality reads as a glyph plus a label for screen readers", () => {
  assert.deepEqual(cardinalityBadge("one_to_one"), { glyph: "1 — 1", label: "一对一" });
  assert.deepEqual(cardinalityBadge("one_to_many"), { glyph: "1 — N", label: "一对多" });
  assert.deepEqual(cardinalityBadge("many_to_one"), { glyph: "N — 1", label: "多对一" });
  // Nobody could measure it, and the row says so instead of going missing.
  assert.deepEqual(cardinalityBadge("unknown"), { glyph: "—", label: "测不出" });
});

test("the two dimensions keep separate vocabularies for their evidence", () => {
  // Mixing the words would imply the two are measuring the same thing.
  const code: Record<TableRelationCodeEvidence, string> = {
    enforced: "强制",
    single_write: "单写",
    batch_allowed: "允许",
    no_write_path: "无写入",
    conflicted: "待人工",
  };
  const database: Record<TableRelationDbEvidence, string> = {
    measured: "已确认",
    low_sample: "样本不足",
    never_written: "死列",
    no_data: "无数据",
  };

  for (const [value, label] of Object.entries(code)) {
    assert.equal(codeEvidenceLabel(value as TableRelationCodeEvidence), label);
  }
  for (const [value, label] of Object.entries(database)) {
    assert.equal(dbEvidenceLabel(value as TableRelationDbEvidence), label);
  }
  // No label is shared, so a badge is never ambiguous about which side it is.
  const overlap = Object.values(code).filter((label) =>
    Object.values(database).includes(label),
  );
  assert.deepEqual(overlap, []);
});

test("a row carries both verdicts in a fixed order, code first", () => {
  // Fixed so the badges line up into columns and a disagreement is visible while
  // scanning down the list rather than only when reading one row closely.
  assert.deepEqual(relationVerdicts(relation()), [
    {
      dimension: "code",
      dimensionLabel: "代码",
      cardinality: "one_to_many",
      glyph: "1 — N",
      cardinalityLabel: "一对多",
      evidenceLabel: "允许",
    },
    {
      dimension: "db",
      dimensionLabel: "数据库",
      cardinality: "one_to_many",
      glyph: "1 — N",
      cardinalityLabel: "一对多",
      evidenceLabel: "已确认",
    },
  ]);
});

test("a disagreement is reported whichever way round it falls", () => {
  assert.equal(dimensionsAgree(relation()), true);

  // The real UAT case: batchInsert allows many cargo rows per order, and all 99
  // orders carry exactly one.
  const diverging = relation({ db_cardinality: "one_to_one", db_evidence: "measured" });
  assert.equal(dimensionsAgree(diverging), false);

  // Seen from the other end the same relation still disagrees.
  assert.equal(
    dimensionsAgree(
      relation({
        direction: "outbound",
        code_cardinality: "many_to_one",
        db_cardinality: "one_to_one",
      }),
    ),
    false,
  );
});

test("a dimension that measured nothing counts as disagreeing, not as agreeing", () => {
  // "the code says one-to-many and nobody could measure it" is the state worth
  // marking; treating an absent verdict as agreement would hide it.
  const unmeasured = relation({ db_cardinality: "unknown", db_evidence: "no_data" });

  assert.equal(dimensionsAgree(unmeasured), false);

  // Both sides unknown do agree: there is nothing to reconcile.
  assert.equal(
    dimensionsAgree(
      relation({
        code_cardinality: "unknown",
        code_evidence: "no_write_path",
        db_cardinality: "unknown",
        db_evidence: "never_written",
      }),
    ),
    true,
  );
});

test("the divergence count is what the footnote promises", () => {
  const relations = [
    relation({ edge_id: "agree" }),
    relation({ edge_id: "diverge", db_cardinality: "one_to_one" }),
    relation({ edge_id: "unmeasured", db_cardinality: "unknown", db_evidence: "no_data" }),
  ];

  assert.equal(disagreementCount(relations), 2);
  assert.equal(disagreementCount([]), 0);
});

test("every evidence value has an explanation the panel can show", () => {
  // The list can only afford the two-character label. A reader deciding whether
  // to trust a verdict needs to know what was and was not established, so every
  // value has to have something to say rather than falling through to blank.
  const code: TableRelationCodeEvidence[] = [
    "enforced",
    "single_write",
    "batch_allowed",
    "no_write_path",
    "conflicted",
  ];
  const database: TableRelationDbEvidence[] = [
    "measured",
    "low_sample",
    "never_written",
    "no_data",
  ];

  for (const value of code) {
    assert.ok(codeEvidenceExplanation(value).length > 0, value);
  }
  for (const value of database) {
    assert.ok(dbEvidenceExplanation(value).length > 0, value);
  }
});

test("a check states the numbers it was decided on", () => {
  // Composed from the counts rather than picked from a table of phrases, so the
  // words and the numbers cannot come apart.
  const cardinality = relationCheckCopy(check("cardinality", "confirmed"), measurement());

  assert.equal(cardinality.title, "每个键几条子行");
  assert.equal(cardinality.outcomeLabel, "通过");
  assert.match(cardinality.summary, /183 行有值/);
  assert.match(cardinality.summary, /49 个键/);
  // 183 over 49 is what makes it one-to-many, so the ratio is stated outright.
  assert.match(cardinality.summary, /平均每个键 3\.7 条/);
});

test("dangling keys are named and counted rather than hinted at", () => {
  const found = relationCheckCopy(check("orphan", "attention"), measurement());
  const clean = relationCheckCopy(
    check("orphan", "confirmed"),
    measurement({ orphan_keys: 0 }),
  );

  assert.equal(found.outcomeLabel, "需关注");
  assert.match(found.summary, /49 个键里有 27 个指不到存活的父行/);
  // Why it matters, not just that it happened.
  assert.match(found.summary, /join 都会把这些子行丢掉/);
  assert.match(clean.summary, /49 个键全部能指到存活的父行/);
});

test("a check with nothing to measure says so instead of reading as a pass", () => {
  const empty = measurement({
    child_table_rows: 0,
    child_rows_with_value: 0,
    child_distinct_keys: 0,
    parent_rows_with_value: 0,
    parent_distinct_keys: 0,
    orphan_keys: 0,
  });
  const dead = measurement({
    child_table_rows: 129,
    child_rows_with_value: 0,
    child_distinct_keys: 0,
    orphan_keys: 0,
  });

  assert.equal(
    relationCheckCopy(check("cardinality", "inconclusive"), empty).summary,
    "整表 0 行，没有可测的内容。",
  );
  assert.equal(
    relationCheckCopy(check("orphan", "inconclusive"), empty).outcomeLabel,
    "未能判定",
  );
  // A dead column and an empty table are different findings, told apart by where
  // the emptiness is.
  assert.match(
    relationCheckCopy(check("cardinality", "inconclusive"), dead).summary,
    /表里 129 行，这一列 0 行有值/,
  );
  assert.match(
    relationCheckCopy(check("parent_unique", "confirmed"), dead).summary,
    /父键唯一/,
  );
});

test("a duplicated parent key undermines the child count and says why", () => {
  const duplicated = measurement({ parent_rows_with_value: 50, parent_distinct_keys: 48 });

  assert.match(
    relationCheckCopy(check("parent_unique", "attention"), duplicated).summary,
    /父键本身有重复/,
  );
  assert.match(
    relationCheckCopy(check("parent_unique", "confirmed"), measurement()).summary,
    /子表侧的计数才站得住/,
  );
});

test("mismatched key kinds are spelled out in both directions", () => {
  const mismatched = measurement({ child_key_kind: "numeric", parent_key_kind: "text" });
  const copy = relationCheckCopy(check("key_kind", "attention"), mismatched);

  assert.equal(copy.title, "两端的键类型");
  assert.match(copy.summary, /子表键是数值，父表键是字符串/);
});

test("the table list sorts the busiest tables first", () => {
  const tables = [
    summary({ table_name: "cs_dsly_line_route", relation_count: 1 }),
    summary({ table_name: "cs_dsly_highway_cargo", relation_count: 4 }),
    summary({ table_name: "cs_dsly_basic_cargo", relation_count: 1 }),
    summary({ table_name: "cs_dsly_basic_port", relation_count: 0 }),
  ];

  assert.deepEqual(
    sortTableSummaries(tables).map((table) => table.table_name),
    [
      "cs_dsly_highway_cargo",
      "cs_dsly_basic_cargo",
      "cs_dsly_line_route",
      "cs_dsly_basic_port",
    ],
  );
});

test("a table reachable only through a dead column reads as unrelated", () => {
  // Its hidden_count is not zero, but nothing about it can be listed, so the
  // only-related switch has to treat it exactly like a table with no relations.
  const tables = [
    summary({ table_name: "cs_dsly_highway_cargo", relation_count: 4 }),
    summary({ table_name: "cs_dsly_dead_only", relation_count: 0, hidden_count: 1 }),
    summary({ table_name: "cs_dsly_basic_port", relation_count: 0 }),
  ];

  assert.equal(unrelatedTableCount(tables), 2);
  assert.deepEqual(
    filterTableSummaries(tables, { search: "", onlyRelated: true }).map((t) => t.table_name),
    ["cs_dsly_highway_cargo"],
  );
});

function site(overrides: Partial<TableRelationCodeSite> = {}): TableRelationCodeSite {
  return {
    kind: "caller_key_reuse",
    role: "write",
    implies: "one_to_many",
    file_path: "backend/c12-mtp/.../HighwayCarrierOrderAdminService.java",
    method_name: "batchCreateCarrierOrder",
    snippet: "cargoDao.batchInsert(insertCargoList);",
    ...overrides,
  };
}

test("write sites and read sites are kept in separate groups", () => {
  // Merged into one list, a groupingBy would sit among the write paths and read
  // as though it created rows. They answer two different questions.
  const groups = groupRelationSites([
    site({ kind: "caller_key_reuse", role: "write" }),
    site({ kind: "lossy_read", role: "read" }),
    site({ kind: "fresh_key_per_row", role: "write", implies: "one_to_one" }),
  ]);

  assert.deepEqual(
    groups.map((group) => [group.role, group.sites.length]),
    [
      ["write", 2],
      ["read", 1],
    ],
  );
});

test("a group with nothing in it is dropped rather than shown empty", () => {
  // A heading with no rows under it invites the reader to wonder what was hidden.
  const groups = groupRelationSites([site({ kind: "single_write", role: "write" })]);

  assert.deepEqual(
    groups.map((group) => group.role),
    ["write"],
  );
});

test("the two batch shapes are described as the different things they are", () => {
  // The distinction that cost four relations a wrong verdict: both reach the
  // database through batchInsert, and only one of them writes several children
  // per parent key.
  assert.match(siteKindExplanation("fresh_key_per_row"), /横着宽/);
  assert.match(siteKindExplanation("caller_key_reuse"), /可以重复/);
  // And the trap: findFirst looks like proof of one and is the opposite.
  assert.match(siteKindExplanation("lossy_read"), /静默丢掉/);
  assert.match(siteKindExplanation("strict_to_map"), /真跑过数据/);

  for (const kind of [
    "fresh_key_per_row",
    "caller_key_reuse",
    "shared_key_fanout",
    "single_write",
    "unique_guard",
    "strict_to_map",
    "lossy_read",
    "grouping_by",
  ] as const) {
    assert.ok(siteKindTitle(kind).length > 0);
    assert.ok(siteKindExplanation(kind).length > 0);
  }
});

test("no recorded sites is distinguished from having found no write path", () => {
  // Two very different claims. One says nobody has written the places down; the
  // other says the code was read and there is nothing there.
  assert.equal(missingSitesNote(relation({ code_evidence: "no_write_path" })), null);
  assert.match(
    missingSitesNote(relation({ code_evidence: "batch_allowed" })) ?? "",
    /还没录入/,
  );
});

test("table persist kinds name the call rather than the parent key", () => {
  assert.equal(writeKindTitle("batch_insert"), "批量插入");
  assert.match(writeKindExplanation("batch_insert"), /batchInsert/);
  assert.equal(writeKindTitle("batch_update"), "批量更新");
  assert.match(writeKindExplanation("batch_update"), /batchUpdate/);
  assert.match(missingWritesNote(), /插入入口还没录入/);
  assert.match(missingUpdatesNote(), /更新入口还没录入/);
});

test("the only-related switch hides tables without relations and search narrows further", () => {
  const tables = [
    summary({ table_name: "cs_dsly_highway_cargo", relation_count: 4 }),
    summary({ table_name: "cs_dsly_basic_port", relation_count: 0 }),
    summary({
      table_name: "cs_dsly_shipping_cargo",
      relation_count: 1,
      database_key: "c12_mtp_db",
    }),
  ];
  const filter = { search: "", onlyRelated: true };

  assert.deepEqual(
    filterTableSummaries(tables, filter).map((t) => t.table_name),
    ["cs_dsly_highway_cargo", "cs_dsly_shipping_cargo"],
  );
  assert.deepEqual(
    filterTableSummaries(tables, { ...filter, onlyRelated: false }).map((t) => t.table_name),
    ["cs_dsly_highway_cargo", "cs_dsly_basic_port", "cs_dsly_shipping_cargo"],
  );
  assert.deepEqual(
    filterTableSummaries(tables, { ...filter, search: "shipping" }).map((t) => t.table_name),
    ["cs_dsly_shipping_cargo"],
  );
  assert.deepEqual(
    filterTableSummaries(tables, { ...filter, onlyRelated: false, search: "port" }).map(
      (t) => t.table_name,
    ),
    ["cs_dsly_basic_port"],
  );
});

test("database key filter keeps only tables from the chosen alias", () => {
  const tables = [
    summary({
      table_name: "cs_dsly_highway_cargo",
      relation_count: 4,
      database_key: "c12_mtp_db",
    }),
    summary({
      table_name: "cs_rcc_risk_event",
      relation_count: 2,
      database_key: "c12_rcc_db",
    }),
    summary({
      table_name: "cs_dsly_basic_port",
      relation_count: 0,
      database_key: "c12_mtp_db",
    }),
  ];

  assert.deepEqual(
    filterTableSummaries(tables, {
      search: "",
      onlyRelated: false,
      databaseKey: "c12_mtp_db",
    }).map((t) => t.table_name),
    ["cs_dsly_highway_cargo", "cs_dsly_basic_port"],
  );
  assert.deepEqual(
    filterTableSummaries(tables, {
      search: "",
      onlyRelated: true,
      databaseKey: "c12_mtp_db",
    }).map((t) => t.table_name),
    ["cs_dsly_highway_cargo"],
  );
  assert.deepEqual(
    filterTableSummaries(tables, {
      search: "risk",
      onlyRelated: true,
      databaseKey: "c12_rcc_db",
    }).map((t) => t.table_name),
    ["cs_rcc_risk_event"],
  );
});
