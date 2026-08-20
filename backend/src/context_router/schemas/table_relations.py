from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

TableRelationEnvironment = str
TableRelationGenerationStatus = Literal["building", "published", "superseded", "failed"]
TableRelationOrientation = Literal["left_to_right", "right_to_left", "undirected"]

# Stored cardinalities are parent-to-child and can only be one, many, or nothing
# established. ``many_to_one`` is added here because it is what the same relation
# reads as from the child's end, which is the end the page is usually looking
# from. ``unknown`` reaches the client rather than being filtered out: with the
# evidence stated alongside it, "nobody could measure this" is an answer.
TableRelationCardinality = Literal[
    "one_to_one",
    "one_to_many",
    "many_to_one",
    "unknown",
]

# What the write paths permit.
TableRelationCodeEvidence = Literal[
    "enforced",  # 强制：违反会抛异常
    "single_write",  # 单写：只有单体写入路径，没有强制
    "batch_allowed",  # 允许：批量写入或循环赋父键
    "no_write_path",  # 无写入：找不到赋值点
    "conflicted",  # 待人工：证据矛盾或目标表不确定
]

# What the rows currently contain.
TableRelationDbEvidence = Literal[
    "measured",  # 已确认：去重比测出且样本过阈值
    "low_sample",  # 样本不足：键数等于行数，但行数太少
    "never_written",  # 死列：表有数据，这一列没有
    "no_data",  # 无数据：整表为空
]

# ``self`` is neither: a column pointing at its own table is one relation seen
# from both ends at once, so it is stated once rather than twice.
TableRelationDirection = Literal["outbound", "inbound", "self"]

# Whether a key is counted as a number or as a string. This is the one property of
# an endpoint that cannot be inferred from its name, and it decides how an unset
# value is spelled, so a probe cannot be written without it.
TableRelationKeyKind = Literal["numeric", "text"]

# What a place in the source is doing that decides how many children a parent key
# gets. These name the deciding circumstance and not the persistence call on
# purpose: the same ``batchInsert`` sits under ``fresh_key_per_row`` and under
# ``caller_key_reuse``, and telling those two apart is the whole difference
# between one child per key and several.
TableRelationCodeSiteKind = Literal[
    "fresh_key_per_row",  # 循环内新生成父键，每个键只挂一行
    "caller_key_reuse",  # 父键来自入参，同一批里可能重复
    "shared_key_fanout",  # 父键在循环外定好，多行共用
    "single_write",  # 单对象写入，一次一行
    "unique_guard",  # 写前按父键查重或跳过
    "strict_to_map",  # 读侧严格 toMap，键重复即抛
    "lossy_read",  # 读侧 findFirst，静默丢弃多余行
    "grouping_by",  # 读侧按父键分组成 List
]

# A read cannot create a row, so it never settles a cardinality by itself. Reads
# are kept because they show what the authors took for granted, which is often
# the only thing that explains a verdict a reader finds surprising.
TableRelationSiteRole = Literal["write", "read"]

# How this table is persisted, named after the call rather than after the parent
# key. Relation code sites cannot reuse this vocabulary: the same ``batchInsert``
# is one-to-one or one-to-many depending on how the key is minted, which is why
# those sites name the key-assignment circumstance instead.
TableRelationWriteKind = Literal["batch_insert", "save_or_update", "insert"]
TableRelationUpdateKind = Literal["batch_update", "save_or_update", "update"]


class TableRelationEndpoint(BaseModel):
    database_key: str
    schema_name: str
    table_name: str
    column_name: str | None = None


class TableRelationMeasurement(BaseModel):
    """What inspecting the two tables established, in numbers.

    These are the counts the data verdict was read off rather than an extra
    decoration on it. Publishing them is what turns the verdict from something to
    be taken on faith into something that can be recomputed and contradicted.

    Every count excludes soft-deleted rows and unset keys, which is why the kinds
    travel with them: an unset key is ``0`` in a numeric column and ``''`` in a
    text one, and a count that spelled it the other way would be a different
    number.
    """

    child_key_kind: TableRelationKeyKind
    parent_key_kind: TableRelationKeyKind
    child_table_rows: int = 0
    child_rows_with_value: int = 0
    child_distinct_keys: int = 0
    parent_rows_with_value: int = 0
    parent_distinct_keys: int = 0
    orphan_keys: int = 0

    @property
    def parent_keys_unique(self) -> bool:
        """Whether the key being pointed at occurs at most once up there.

        The precondition the child measurement rests on. Without it, several
        children per key could just as well be one child per key several times
        over, and the relation would not be the one : many it appears to be.
        """
        return (
            self.parent_rows_with_value > 0
            and self.parent_distinct_keys == self.parent_rows_with_value
        )

    @property
    def keys_comparable(self) -> bool:
        return self.child_key_kind == self.parent_key_kind


class TableRelationView(BaseModel):
    """One relation as a row of the flat list.

    ``child`` and ``parent`` name the two ends the same way no matter which table
    is being inspected, which is what makes ``relation_id`` a stable identity: the
    foreign key side is the one thing about a relation that does not move. The two
    cardinalities do move, because they are stated from the inspected table's end.
    """

    edge_id: str
    # The two endpoints written out, e.g. ``sys_user_ext.user_id`` referencing
    # ``sys_user.id``. Both are qualified with the database alias when the two
    # ends live in different databases, where a table name alone is ambiguous.
    # Formatted here so the identity a row shows, a future detail panel looks up,
    # and a search matches on can never be spelled three different ways.
    relation_id: str
    references: str
    child: TableRelationEndpoint
    parent: TableRelationEndpoint
    direction: TableRelationDirection
    code_cardinality: TableRelationCardinality
    code_evidence: TableRelationCodeEvidence
    db_cardinality: TableRelationCardinality
    db_evidence: TableRelationDbEvidence
    code_checked_at: datetime | None = None
    db_measured_at: datetime | None = None
    cross_database: bool = False

    @property
    def dimensions_agree(self) -> bool:
        return self.code_cardinality == self.db_cardinality


class TableRelationGenerationSummary(BaseModel):
    generation_id: str
    revision: int
    environment: TableRelationEnvironment
    status: TableRelationGenerationStatus
    edge_count: int = 0
    # Only relations the page actually renders are counted here.
    relation_count: int = 0
    hidden_count: int = 0
    published_at: datetime | None = None


class TableRelationStatus(BaseModel):
    workspace_id: str
    generation: TableRelationGenerationSummary | None = None
    building: TableRelationGenerationSummary | None = None
    database_keys: list[str] = Field(default_factory=list)
    rebuild_command: str


class TableRelationTableSummary(BaseModel):
    """One row of the table list.

    The list is flat, so a table card needs one number. ``hidden_count`` is the
    dead columns held back from the list, published so the card can offer to
    reveal them without first fetching what it just hid.
    """

    database_key: str
    schema_name: str
    table_name: str
    relation_count: int = 0
    hidden_count: int = 0


class TableRelationTableList(BaseModel):
    workspace_id: str
    generation: TableRelationGenerationSummary | None = None
    only_related: bool = True
    total_count: int = 0
    related_count: int = 0
    returned_count: int = 0
    tables: list[TableRelationTableSummary] = Field(default_factory=list)


class TableRelationTableIdentity(BaseModel):
    database_key: str
    schema_name: str
    table_name: str


class TableRelationTableDetail(BaseModel):
    workspace_id: str
    generation: TableRelationGenerationSummary
    table: TableRelationTableIdentity
    relations: list[TableRelationView] = Field(default_factory=list)
    relation_count: int = 0
    hidden_count: int = 0


# What each check looked at. Kept as a key rather than a sentence because the
# wording belongs with the rest of the page's copy; what the API owes the client
# is the finding and the query that produced it.
TableRelationCheckKey = Literal[
    "cardinality",  # 每个键几条子行
    "parent_unique",  # 被指向的键在父表唯一吗
    "orphan",  # 有多少子键找不到父行
    "key_kind",  # 两端的键类型能不能比
]

# ``inconclusive`` is not a softer ``attention``: one says the check ran and found
# nothing wrong, the other says there was nothing to run it against.
TableRelationCheckOutcome = Literal["confirmed", "attention", "inconclusive"]


class TableRelationCheck(BaseModel):
    """One thing that was checked, and the query that would check it again.

    The SQL is derived from the endpoints on read rather than stored, because a
    saved query string would keep claiming to describe endpoints that had since
    been renamed. Derived, it cannot disagree with the relation it belongs to.
    """

    key: TableRelationCheckKey
    outcome: TableRelationCheckOutcome
    sql: str


class TableRelationCodeSite(BaseModel):
    """One place in the source the code verdict was read off.

    ``role`` and ``implies`` are computed from ``kind`` here rather than sent as
    stored fields, so a site cannot arrive claiming that a ``groupingBy`` writes
    rows or that a fresh key per iteration argues for many children per key.

    There is no line number, deliberately. It is the only coordinate that would
    go on looking exact after an edit moved the code, and a site pointing
    confidently at the wrong line is worse than one that asks the reader to
    search. ``method_name`` survives edits that merely shift lines, and
    ``snippet`` is what makes staleness detectable: if it is no longer in the
    file, the site is out of date and can be made to admit it.
    """

    kind: TableRelationCodeSiteKind
    role: TableRelationSiteRole
    implies: TableRelationCardinality
    # Relative to the workspace root: an absolute path would be one machine's
    # answer to a question about the repository.
    file_path: str
    method_name: str
    snippet: str


class TableRelationDetail(BaseModel):
    """One relation, with the evidence behind both of its verdicts.

    ``relation`` is the same view the list row was built from, cardinalities and
    all, so opening a row cannot show a different verdict than the row it was
    opened from. ``table`` records which end it was opened from, since that is
    what the two cardinalities are stated relative to.

    ``code_sites`` being empty is not the same as there being no write path: the
    latter is stated by ``code_evidence``, and an empty list beside a conclusive
    evidence value means only that nobody has written the places down yet.
    """

    workspace_id: str
    generation: TableRelationGenerationSummary
    table: TableRelationTableIdentity
    relation: TableRelationView
    measurement: TableRelationMeasurement
    checks: list[TableRelationCheck] = Field(default_factory=list)
    code_sites: list[TableRelationCodeSite] = Field(default_factory=list)


class TableRelationWriteSite(BaseModel):
    """One place that persists rows of the currently selected table.

    Not a relation code site. Those hang on an edge and say how a parent key is
    assigned; this hangs on a table and says which call writes its rows. The same
    method may appear under both, and that is not duplication — they answer
    different questions.
    """

    kind: TableRelationWriteKind
    file_path: str
    method_name: str
    snippet: str


class TableRelationTableWrites(BaseModel):
    """The insert calls recorded for one table.

    An empty ``writes`` is not a claim that nothing inserts into the table. It
    means nobody has written the places down yet, which is the same distinction
    the relation evidence panel already has to make for missing code sites.
    """

    workspace_id: str
    generation: TableRelationGenerationSummary
    table: TableRelationTableIdentity
    writes: list[TableRelationWriteSite] = Field(default_factory=list)


class TableRelationUpdateSite(BaseModel):
    """One place that updates rows of the currently selected table.

    Independent of insert sites. The same method may appear under both when it
    inserts and later updates, and that is not duplication — they answer
    different questions.
    """

    kind: TableRelationUpdateKind
    file_path: str
    method_name: str
    snippet: str


class TableRelationTableUpdates(BaseModel):
    """The update calls recorded for one table.

    An empty ``updates`` is not a claim that nothing updates the table. It means
    nobody has written the places down yet.
    """

    workspace_id: str
    generation: TableRelationGenerationSummary
    table: TableRelationTableIdentity
    updates: list[TableRelationUpdateSite] = Field(default_factory=list)
