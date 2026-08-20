import type {
  TableRelationCardinality,
  TableRelationCheck,
  TableRelationCheckOutcome,
  TableRelationCodeEvidence,
  TableRelationCodeSite,
  TableRelationCodeSiteKind,
  TableRelationDbEvidence,
  TableRelationMeasurement,
  TableRelationSiteRole,
  TableRelationTableSummary,
  TableRelationView,
  TableRelationPersistKind,
} from "@/lib/types";

/**
 * A cardinality reads as a glyph plus a spelled-out label. The glyph alone
 * carries the shape and the label is what assistive technology announces, so no
 * state here depends on colour.
 */
export interface CardinalityBadge {
  glyph: string;
  label: string;
}

const CARDINALITY_BADGES: Record<TableRelationCardinality, CardinalityBadge> = {
  one_to_one: { glyph: "1 — 1", label: "一对一" },
  one_to_many: { glyph: "1 — N", label: "一对多" },
  many_to_one: { glyph: "N — 1", label: "多对一" },
  unknown: { glyph: "—", label: "测不出" },
};

/**
 * The evidence a verdict rests on, in two vocabularies that stay apart on
 * purpose: the code dimension answers what the write paths permit, the data
 * dimension answers what the rows contain, and mixing the words would suggest
 * the two are measuring the same thing.
 */
const CODE_EVIDENCE_LABELS: Record<TableRelationCodeEvidence, string> = {
  enforced: "强制",
  single_write: "单写",
  batch_allowed: "允许",
  no_write_path: "无写入",
  conflicted: "待人工",
};

const DB_EVIDENCE_LABELS: Record<TableRelationDbEvidence, string> = {
  measured: "已确认",
  low_sample: "样本不足",
  never_written: "死列",
  no_data: "无数据",
};

export function cardinalityBadge(cardinality: TableRelationCardinality): CardinalityBadge {
  return CARDINALITY_BADGES[cardinality];
}

export function codeEvidenceLabel(evidence: TableRelationCodeEvidence): string {
  return CODE_EVIDENCE_LABELS[evidence];
}

export function dbEvidenceLabel(evidence: TableRelationDbEvidence): string {
  return DB_EVIDENCE_LABELS[evidence];
}

/** One dimension of a row, ready to render without the caller knowing which. */
export interface RelationVerdict {
  dimension: "code" | "db";
  dimensionLabel: string;
  cardinality: TableRelationCardinality;
  glyph: string;
  cardinalityLabel: string;
  evidenceLabel: string;
}

/**
 * Both verdicts in a fixed order, code first.
 *
 * Fixed because the two are compared by eye far more often than they are read
 * one at a time: a row whose dimensions swap places between renders would make
 * a disagreement impossible to spot while scanning a column.
 */
export function relationVerdicts(relation: TableRelationView): RelationVerdict[] {
  return [
    {
      dimension: "code",
      dimensionLabel: "代码",
      cardinality: relation.code_cardinality,
      glyph: cardinalityBadge(relation.code_cardinality).glyph,
      cardinalityLabel: cardinalityBadge(relation.code_cardinality).label,
      evidenceLabel: codeEvidenceLabel(relation.code_evidence),
    },
    {
      dimension: "db",
      dimensionLabel: "数据库",
      cardinality: relation.db_cardinality,
      glyph: cardinalityBadge(relation.db_cardinality).glyph,
      cardinalityLabel: cardinalityBadge(relation.db_cardinality).label,
      evidenceLabel: dbEvidenceLabel(relation.db_evidence),
    },
  ];
}

/**
 * Whether the two dimensions reached the same cardinality.
 *
 * A row where one side is `unknown` counts as disagreeing, which is deliberate:
 * "the code says one-to-many and nobody could measure it" is exactly the state
 * worth marking, and treating an absent verdict as agreement would hide it.
 */
export function dimensionsAgree(relation: TableRelationView): boolean {
  return relation.code_cardinality === relation.db_cardinality;
}

/** Rows on this table whose two dimensions reached different answers. */
export function disagreementCount(relations: TableRelationView[]): number {
  return relations.filter((relation) => !dimensionsAgree(relation)).length;
}

/**
 * What an evidence value actually means, spelled out for the panel that has room
 * for it. The list can only afford the two-character label; a reader deciding
 * whether to trust a verdict needs to know what was and was not established.
 *
 * The code entries carry a second job. A verdict here was reached by reading the
 * write paths, not by compiling them, so the wording says what was seen rather
 * than what is guaranteed — "结构上不限条数" is a true statement about the code
 * whether or not the rows ever exercise it.
 */
const CODE_EVIDENCE_EXPLANATIONS: Record<TableRelationCodeEvidence, string> = {
  enforced: "写入路径上有唯一性校验，多写第二条会抛异常。",
  single_write: "只有单体写入路径，但没有强制校验，多写一条不会报错。",
  batch_allowed: "批量写入，或者循环给子集合逐条赋父键，结构上不限条数。",
  no_write_path: "代码里找不到给这一列赋值的地方，可能走外部 SQL 或消息写入。",
  conflicted: "证据互相矛盾，或者指向的表不唯一，需要人工判断。",
};

const DB_EVIDENCE_EXPLANATIONS: Record<TableRelationDbEvidence, string> = {
  measured: "有值行数和去重键数都测到了，样本量足够下结论。",
  low_sample: "每个键目前只有一条子行，但行数太少，不能排除只是还没出现重复。",
  never_written: "表里有数据，这一列一行都没有值。",
  no_data: "整表没有数据，这个维度测不出任何结论。",
};

export function codeEvidenceExplanation(evidence: TableRelationCodeEvidence): string {
  return CODE_EVIDENCE_EXPLANATIONS[evidence];
}

export function dbEvidenceExplanation(evidence: TableRelationDbEvidence): string {
  return DB_EVIDENCE_EXPLANATIONS[evidence];
}

const CHECK_TITLES: Record<TableRelationCheck["key"], string> = {
  cardinality: "每个键几条子行",
  parent_unique: "父键在父表里唯一吗",
  orphan: "有没有指不到父行的键",
  key_kind: "两端的键类型",
};

// Deliberately not "已确认": that is already the label of the `measured` evidence,
// and a check passing is a different claim from a cardinality being measured.
const CHECK_OUTCOME_LABELS: Record<TableRelationCheckOutcome, string> = {
  confirmed: "通过",
  attention: "需关注",
  inconclusive: "未能判定",
};

export interface RelationCheckCopy {
  title: string;
  outcomeLabel: string;
  summary: string;
}

/**
 * One check written out as the panel says it.
 *
 * Every sentence is composed from the stored counts rather than picked from a
 * table of phrases, so the words and the numbers cannot come apart: there is no
 * way to render "全部能指到父行" for a relation whose orphan count is 27.
 */
export function relationCheckCopy(
  check: TableRelationCheck,
  measurement: TableRelationMeasurement,
): RelationCheckCopy {
  return {
    title: CHECK_TITLES[check.key],
    outcomeLabel: CHECK_OUTCOME_LABELS[check.outcome],
    summary: checkSummary(check, measurement),
  };
}

function checkSummary(
  check: TableRelationCheck,
  measurement: TableRelationMeasurement,
): string {
  switch (check.key) {
    case "cardinality":
      return cardinalitySummary(measurement);
    case "parent_unique":
      return parentUniqueSummary(measurement);
    case "orphan":
      return orphanSummary(measurement);
    case "key_kind":
      return `子表键是${keyKindLabel(measurement.child_key_kind)}，父表键是${keyKindLabel(
        measurement.parent_key_kind,
      )}，两端类型不同，join 不一定成立。`;
  }
}

function cardinalitySummary(measurement: TableRelationMeasurement): string {
  const { child_table_rows, child_rows_with_value, child_distinct_keys } = measurement;
  if (child_table_rows === 0) return "整表 0 行，没有可测的内容。";
  if (child_rows_with_value === 0) {
    return `表里 ${count(child_table_rows)} 行，这一列 0 行有值。`;
  }
  const measured =
    `表里 ${count(child_table_rows)} 行，这一列 ${count(child_rows_with_value)} 行有值，` +
    `去重后 ${count(child_distinct_keys)} 个键`;
  if (child_distinct_keys === child_rows_with_value) {
    return `${measured}，每个键正好一条子行。`;
  }
  const perKey = (child_rows_with_value / child_distinct_keys).toFixed(1);
  return `${measured}，平均每个键 ${perKey} 条子行。`;
}

function parentUniqueSummary(measurement: TableRelationMeasurement): string {
  const { parent_rows_with_value, parent_distinct_keys } = measurement;
  if (parent_rows_with_value === 0) return "父表这一列 0 行有值，无从检查。";
  const measured =
    `父表 ${count(parent_rows_with_value)} 行有值，` +
    `去重后 ${count(parent_distinct_keys)} 个键`;
  if (parent_distinct_keys === parent_rows_with_value) {
    return `${measured}，父键唯一，子表侧的计数才站得住。`;
  }
  return `${measured}，父键本身有重复，子表侧的基数结论不可靠。`;
}

function orphanSummary(measurement: TableRelationMeasurement): string {
  const { child_distinct_keys, orphan_keys } = measurement;
  if (child_distinct_keys === 0) return "这一列没有值，无从检查。";
  if (orphan_keys === 0) {
    return `${count(child_distinct_keys)} 个键全部能指到存活的父行。`;
  }
  return (
    `${count(child_distinct_keys)} 个键里有 ${count(orphan_keys)} 个指不到存活的父行，` +
    `要么父行不存在，要么已被逻辑删除，join 都会把这些子行丢掉。`
  );
}

function keyKindLabel(kind: TableRelationMeasurement["child_key_kind"]): string {
  return kind === "numeric" ? "数值" : "字符串";
}

/**
 * What each kind of site is, and why it settles the multiplicity it settles.
 *
 * The two batch entries are the reason this vocabulary exists. Both reach the
 * database through the same call, and reading the first as the second is how four
 * relations here came to carry the wrong code verdict for months: a batch of one
 * child per freshly minted key is wide, not deep.
 */
const SITE_KIND_TITLES: Record<TableRelationCodeSiteKind, string> = {
  fresh_key_per_row: "循环里新生成父键，一键一行",
  caller_key_reuse: "父键由入参带进来",
  shared_key_fanout: "父键在循环外定好，多行共用",
  single_write: "单对象写入",
  unique_guard: "写前按父键查重",
  strict_to_map: "读侧严格 toMap",
  lossy_read: "读侧只取第一条",
  grouping_by: "读侧按父键分组",
};

const SITE_KIND_EXPLANATIONS: Record<TableRelationCodeSiteKind, string> = {
  fresh_key_per_row:
    "每次迭代都新生成一个父键，再挂上一条子行。批量写入在这里是横着宽，不是竖着深。",
  caller_key_reuse:
    "父键来自调用方传进来的数据，同一批里可以重复，写入路径上没有任何东西阻止。",
  shared_key_fanout: "父键在进入循环前就定好了，循环里每条子行都用它。",
  single_write: "一次调用写一条，但没有校验挡住第二次调用再写一条。",
  unique_guard: "父键已存在就跳过或报错，这一条路径上写不出第二行。",
  strict_to_map:
    "toMap 没有合并函数，键一重复就抛 IllegalStateException。这一条只在真跑过数据时才算运行时验证。",
  lossy_read:
    "findFirst 会静默丢掉多余的行。这一类看着像 1:1 的证据，其实说明作者预期可能有多条。",
  grouping_by: "按父键分组成 List，类型本身就说明预期不止一条。",
};

export function siteKindTitle(kind: TableRelationCodeSiteKind): string {
  return SITE_KIND_TITLES[kind];
}

export function siteKindExplanation(kind: TableRelationCodeSiteKind): string {
  return SITE_KIND_EXPLANATIONS[kind];
}

export interface RelationSiteGroup {
  role: TableRelationSiteRole;
  title: string;
  /** Said once per group rather than per site, where it would be noise. */
  note: string;
  sites: TableRelationCodeSite[];
}

/**
 * Sites split into what puts the key there and what merely consumes it.
 *
 * Two questions, not one. Merged into a single list, a `groupingBy` would sit
 * among the write paths and read as though it created rows. Empty groups are
 * dropped: a heading with nothing under it invites the reader to wonder what was
 * hidden.
 */
export function groupRelationSites(sites: TableRelationCodeSite[]): RelationSiteGroup[] {
  const groups: RelationSiteGroup[] = [
    {
      role: "write",
      title: "写入入口",
      note: "决定基数的是这些：能写出第二条的路径存在，关系就是一对多。",
      sites: sites.filter((site) => site.role === "write"),
    },
    {
      role: "read",
      title: "读取方式",
      note: "读不出行，所以不单独决定基数；它显示的是作者当时认定的形状。",
      sites: sites.filter((site) => site.role === "read"),
    },
  ];
  return groups.filter((group) => group.sites.length > 0);
}

/**
 * How the code dimension should describe its own silence.
 *
 * Returns null when there is nothing to explain. The distinction matters: no
 * sites beside `no_write_path` is a complete answer, and no sites beside a
 * conclusive verdict means only that nobody has written the places down.
 */
export function missingSitesNote(relation: TableRelationView): string | null {
  if (relation.code_evidence === "no_write_path") return null;
  return "这条关系的结论已经给出，但写入点位还没录入，暂时只能看依据类型。";
}

const PERSIST_KIND_TITLES: Record<TableRelationPersistKind, string> = {
  batch_insert: "批量插入",
  save_or_update: "单对象保存",
  insert: "单次插入",
  batch_update: "批量更新",
  update: "单次更新",
};

const PERSIST_KIND_EXPLANATIONS: Record<TableRelationPersistKind, string> = {
  batch_insert: "一次调用写入多行，循环里收集后再交给 batchInsert。",
  save_or_update: "一次调用写一行，走 saveOrUpdate。",
  insert: "一次插入一行。",
  batch_update: "一次调用更新多行，循环里收集后再交给 batchUpdate。",
  update: "一次更新已有行。",
};

export function writeKindTitle(kind: TableRelationPersistKind): string {
  return PERSIST_KIND_TITLES[kind];
}

export function writeKindExplanation(kind: TableRelationPersistKind): string {
  return PERSIST_KIND_EXPLANATIONS[kind];
}

export function missingWritesNote(): string {
  return "这张表的插入入口还没录入。";
}

export function missingUpdatesNote(): string {
  return "这张表的更新入口还没录入。";
}

function count(value: number): string {
  return value.toLocaleString("zh-CN");
}

export interface TableFilter {
  search: string;
  onlyRelated: boolean;
  /** Empty string means every database. */
  databaseKey?: string;
}

export function filterTableSummaries(
  tables: TableRelationTableSummary[],
  { search, onlyRelated, databaseKey = "" }: TableFilter,
): TableRelationTableSummary[] {
  const needle = search.trim().toLocaleLowerCase();
  const database = databaseKey.trim();
  return tables.filter((table) => {
    if (database && table.database_key !== database) return false;
    if (onlyRelated && table.relation_count === 0) return false;
    if (!needle) return true;
    return (
      table.table_name.toLocaleLowerCase().includes(needle) ||
      table.database_key.toLocaleLowerCase().includes(needle)
    );
  });
}

/** Distinct database aliases from the published table list, sorted. */
export function listDatabaseKeys(tables: TableRelationTableSummary[]): string[] {
  return [...new Set(tables.map((table) => table.database_key))].sort((left, right) =>
    left.localeCompare(right),
  );
}

export function unrelatedTableCount(tables: TableRelationTableSummary[]): number {
  return tables.filter((table) => table.relation_count === 0).length;
}

/** Busiest tables first so the interesting ones are reachable without scrolling. */
export function sortTableSummaries(
  tables: TableRelationTableSummary[],
): TableRelationTableSummary[] {
  return [...tables].sort((left, right) => {
    if (left.relation_count !== right.relation_count) {
      return right.relation_count - left.relation_count;
    }
    if (left.database_key !== right.database_key) {
      return left.database_key.localeCompare(right.database_key);
    }
    return left.table_name.localeCompare(right.table_name);
  });
}

export function tableKey(table: {
  database_key: string;
  schema_name: string;
  table_name: string;
}): string {
  return `${table.database_key}.${table.schema_name}.${table.table_name}`;
}
