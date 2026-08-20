"""Rules every table relation writer and reader has to agree on.

These live in their own module because two very different callers need the exact
same answers: the read projection decides what the page is allowed to show, and
whatever writes relations (today the seed script, later a build pipeline) has to
store counters that match what the page will render. Keeping one copy means the
left-hand table counts can never drift from the rows in the list.

A relation is adjudicated along two independent dimensions. The code dimension
answers what the write paths permit; the data dimension answers what the rows
currently contain. They are allowed to disagree, and a disagreement is a finding
rather than an error, so neither dimension is derived from the other and neither
overrides the other.
"""

from __future__ import annotations

from typing import cast

from context_router.schemas.table_relations import (
    TableRelationCardinality,
    TableRelationCodeEvidence,
    TableRelationCodeSiteKind,
    TableRelationDbEvidence,
    TableRelationKeyKind,
    TableRelationMeasurement,
    TableRelationSiteRole,
    TableRelationUpdateKind,
    TableRelationWriteKind,
)

# Bookkeeping columns every table in these databases carries. They never take
# part in a relation, so nothing about them ever reaches the page. Matching is
# on the exact column name, not a prefix or a substring: ``company_id`` is
# excluded while ``affiliation_company_id`` is a perfectly normal foreign key.
COMMON_COLUMNS: frozenset[str] = frozenset(
    {
        "deleted",
        "tenancy",
        "company_id",
        "creator",
        "create_time",
        "modifier",
        "modify_time",
    }
)

# What a stored cardinality is allowed to be. Both dimensions are persisted
# parent-to-child, and a parent row has either one child or many, so these three
# exhaust the possibilities. ``many_to_one`` exists only as a reading of the same
# relation from the child's end, which ``flip_cardinality`` produces.
STORED_CARDINALITIES: frozenset[str] = frozenset({"one_to_one", "one_to_many", "unknown"})

# The evidence that establishes no multiplicity at all. Pairing one of these with
# anything other than ``unknown`` would let a row claim to know the cardinality
# while admitting it never found anything to measure.
_INCONCLUSIVE_CODE: frozenset[str] = frozenset({"no_write_path", "conflicted"})
_INCONCLUSIVE_DB: frozenset[str] = frozenset({"never_written", "no_data"})

CODE_EVIDENCES: frozenset[str] = frozenset(
    {"enforced", "single_write", "batch_allowed"} | _INCONCLUSIVE_CODE
)
DB_EVIDENCES: frozenset[str] = frozenset({"measured", "low_sample"} | _INCONCLUSIVE_DB)

KEY_KINDS: frozenset[str] = frozenset({"numeric", "text"})

# What a place in the source can be doing that settles how many children a parent
# key gets. These name the deciding circumstance rather than the persistence call,
# and the difference is not pedantry: ``batchInsert`` appears under both
# ``fresh_key_per_row`` and ``caller_key_reuse``, so a vocabulary built out of
# call names cannot tell a batch of one-child-each from a batch that piles several
# children onto one key. Reading a ``batchInsert`` as the second when it was the
# first is exactly how four relations came to carry a wrong code verdict.
_SITE_IMPLIES_ONE: frozenset[str] = frozenset(
    {
        # A fresh parent key is minted inside the loop and one child is attached
        # to it, so the batch is wide in keys rather than deep in children.
        "fresh_key_per_row",
        # One child object written per call, with nothing to stop a later call.
        "single_write",
        # The write is skipped when the key is already present.
        "unique_guard",
        # ``Collectors.toMap`` with no merge function: a repeated key throws.
        "strict_to_map",
    }
)
_SITE_IMPLIES_MANY: frozenset[str] = frozenset(
    {
        # The parent key arrives from the caller, so one batch can carry the same
        # key twice and nothing in the write path objects.
        "caller_key_reuse",
        # The key is fixed before the loop and every child in it gets that key.
        "shared_key_fanout",
        # ``findFirst``: extra rows are dropped in silence. The trap of the set --
        # it reads like proof of one and is really an author allowing for several.
        "lossy_read",
        # Grouped into a list per key, which is a list because it can hold more.
        "grouping_by",
    }
)
CODE_SITE_KINDS: frozenset[str] = _SITE_IMPLIES_ONE | _SITE_IMPLIES_MANY

# Reads cannot create a row, so they never decide a cardinality on their own; they
# are kept because they show what the authors believed while writing the other
# side, which is often the only thing that explains a verdict a reader disputes.
_READ_SITES: frozenset[str] = frozenset({"strict_to_map", "lossy_read", "grouping_by"})

# Which kind of site entitles a verdict to each grade of evidence. ``conflicted``
# is absent on purpose: it is the state a human is asked to settle, so it is the
# one verdict that may stand over sites pointing in opposite directions.
_EVIDENCE_NEEDS: dict[str, frozenset[str]] = {
    "enforced": frozenset({"unique_guard", "strict_to_map"}),
    "single_write": frozenset({"fresh_key_per_row", "single_write"}),
    "batch_allowed": frozenset({"caller_key_reuse", "shared_key_fanout"}),
}

# How many rows a table has to hold before one key per row is read as one-to-one
# rather than as a collision that has not happened yet. A tuning number, so it
# lives here and deliberately not in a check constraint: retuning it has to be
# able to change how stored rows are read without invalidating any of them.
LOW_SAMPLE_ROW_THRESHOLD = 20

_FLIPPED: dict[str, TableRelationCardinality] = {
    "one_to_one": "one_to_one",
    "one_to_many": "many_to_one",
    "many_to_one": "one_to_many",
    "unknown": "unknown",
}


def is_common_column(column_name: str) -> bool:
    return column_name.strip().casefold() in COMMON_COLUMNS


def flip_cardinality(cardinality: str) -> TableRelationCardinality:
    """Re-express a parent-to-child cardinality from the child's point of view.

    Total over every value either dimension can hold, ``unknown`` included: a
    relation nobody could measure reads the same from both ends, and the page
    states that rather than dropping the row.
    """
    flipped = _FLIPPED.get(cardinality)
    if flipped is None:
        raise ValueError(f"基数 {cardinality!r} 不是可存储的取值")
    return flipped


def as_cardinality(cardinality: str) -> TableRelationCardinality:
    if cardinality not in _FLIPPED:
        raise ValueError(f"基数 {cardinality!r} 不是可存储的取值")
    return cast(TableRelationCardinality, cardinality)


def as_code_evidence(evidence: str) -> TableRelationCodeEvidence:
    if evidence not in CODE_EVIDENCES:
        raise ValueError(f"代码依据 {evidence!r} 不是可存储的取值")
    return cast(TableRelationCodeEvidence, evidence)


def as_db_evidence(evidence: str) -> TableRelationDbEvidence:
    if evidence not in DB_EVIDENCES:
        raise ValueError(f"数据依据 {evidence!r} 不是可存储的取值")
    return cast(TableRelationDbEvidence, evidence)


def as_key_kind(kind: str) -> TableRelationKeyKind:
    if kind not in KEY_KINDS:
        raise ValueError(f"键类型 {kind!r} 只能是 {sorted(KEY_KINDS)} 之一")
    return cast(TableRelationKeyKind, kind)


def as_site_kind(kind: str) -> TableRelationCodeSiteKind:
    if kind not in CODE_SITE_KINDS:
        raise ValueError(f"代码点位类型 {kind!r} 不是可存储的取值")
    return cast(TableRelationCodeSiteKind, kind)


WRITE_KINDS: frozenset[str] = frozenset({"batch_insert", "save_or_update", "insert"})
UPDATE_KINDS: frozenset[str] = frozenset({"batch_update", "save_or_update", "update"})


def as_write_kind(kind: str) -> TableRelationWriteKind:
    if kind not in WRITE_KINDS:
        raise ValueError(f"插入入口类型 {kind!r} 不是可存储的取值")
    return cast(TableRelationWriteKind, kind)


def as_update_kind(kind: str) -> TableRelationUpdateKind:
    if kind not in UPDATE_KINDS:
        raise ValueError(f"更新入口类型 {kind!r} 不是可存储的取值")
    return cast(TableRelationUpdateKind, kind)


def check_write_site(*, kind: str, file_path: str, method_name: str, snippet: str) -> None:
    """Reject an insert call that could not be found again.

    The same location rules as relation code sites, for the same reason: an
    absolute path is one machine's answer, a missing method cannot be searched
    for, and a whole-file snippet is no longer a site.
    """
    as_write_kind(kind)
    if not file_path or file_path.startswith("/") or not method_name:
        raise ValueError("插入入口必须有相对路径和方法名")
    if not 1 <= len(snippet) <= 2000:
        raise ValueError("插入入口的片段长度必须在 1 到 2000 之间")


def check_update_site(*, kind: str, file_path: str, method_name: str, snippet: str) -> None:
    """Reject an update call that could not be found again."""
    as_update_kind(kind)
    if not file_path or file_path.startswith("/") or not method_name:
        raise ValueError("更新入口必须有相对路径和方法名")
    if not 1 <= len(snippet) <= 2000:
        raise ValueError("更新入口的片段长度必须在 1 到 2000 之间")


def site_role(kind: str) -> TableRelationSiteRole:
    """Whether this site puts the key there or merely consumes it.

    Derived rather than stored, and kept out of the page's two lists as a
    computed thing, because a site that claimed a role its kind contradicts
    would be a row asserting that ``groupingBy`` writes to the database.
    """
    return "read" if as_site_kind(kind) in _READ_SITES else "write"


def site_implication(kind: str) -> TableRelationCardinality:
    """The multiplicity this site on its own would argue for."""
    return "one_to_one" if as_site_kind(kind) in _SITE_IMPLIES_ONE else "one_to_many"


def check_sites(
    *,
    code_cardinality: str,
    code_evidence: str,
    site_kinds: tuple[str, ...],
) -> None:
    """Reject a code verdict none of its own sites argues for.

    This is the invariant the code dimension was missing while it had nothing
    but a label to show. It earned itself immediately: four relations were
    stored as ``one_to_many`` on ``batch_allowed`` evidence, and once their
    sites were written down not one of the sites implied many. An unsupported
    verdict now fails where it is built.

    What is deliberately not checked is sites pointing both ways. A path that
    can write several children and another that writes one do not contradict
    each other -- the first one settles it, and the relation is one-to-many
    because a possibility is enough. Only a human calling it ``conflicted``
    means the evidence itself could not be reconciled.
    """
    kinds = tuple(as_site_kind(kind) for kind in site_kinds)
    as_code_evidence(code_evidence)
    writes = tuple(kind for kind in kinds if site_role(kind) == "write")
    if code_evidence == "no_write_path" and writes:
        raise ValueError(f"依据是无写入路径，却记了 {len(writes)} 处写入点位")
    if not kinds:
        return
    if code_cardinality != "unknown" and not any(
        site_implication(kind) == code_cardinality for kind in kinds
    ):
        raise ValueError(f"没有任何点位支持基数 {code_cardinality!r}")
    needed = _EVIDENCE_NEEDS.get(code_evidence)
    if needed is not None and not needed & set(kinds):
        raise ValueError(f"依据 {code_evidence!r} 需要 {sorted(needed)} 里的点位作为支撑")


def check_counts(measurement: TableRelationMeasurement) -> None:
    """Reject counts that cannot all be true of the same two tables.

    Only arithmetic, not judgement: a key cannot be distinct more often than it
    occurs, occur more often than there are rows, or dangle more often than it
    occurs. Whoever supplies the numbers is trusted about what they measured and
    not about having typed it consistently.
    """
    as_key_kind(measurement.child_key_kind)
    as_key_kind(measurement.parent_key_kind)
    counts = (
        measurement.child_table_rows,
        measurement.child_rows_with_value,
        measurement.child_distinct_keys,
        measurement.parent_rows_with_value,
        measurement.parent_distinct_keys,
        measurement.orphan_keys,
    )
    if any(count < 0 for count in counts):
        raise ValueError("实测计数不能为负数")
    if measurement.child_distinct_keys > measurement.child_rows_with_value:
        raise ValueError("子表去重键数不能超过有值行数")
    if measurement.child_rows_with_value > measurement.child_table_rows:
        raise ValueError("子表有值行数不能超过总行数")
    if measurement.parent_distinct_keys > measurement.parent_rows_with_value:
        raise ValueError("父表去重键数不能超过有值行数")
    if measurement.orphan_keys > measurement.child_distinct_keys:
        raise ValueError("孤儿键数不能超过子表去重键数")


def db_verdict_from_counts(
    measurement: TableRelationMeasurement,
) -> tuple[TableRelationCardinality, TableRelationDbEvidence]:
    """Read the data verdict off the counts, which is the only place it comes from.

    Derived rather than declared so the verdict and its numbers cannot be made to
    disagree by a typo: the check constraints that guard this pairing in storage
    should be unreachable from any writer that goes through here.

    One key per row reads as one-to-one only once there are enough rows for a
    collision to have had a chance to happen. A repeated key needs no such
    allowance in the other direction: having seen the same key twice, the sample
    size no longer matters.
    """
    if measurement.child_table_rows == 0:
        return "unknown", "no_data"
    if measurement.child_rows_with_value == 0:
        return "unknown", "never_written"
    if measurement.child_distinct_keys < measurement.child_rows_with_value:
        return "one_to_many", "measured"
    if measurement.child_rows_with_value < LOW_SAMPLE_ROW_THRESHOLD:
        return "one_to_one", "low_sample"
    return "one_to_one", "measured"


def is_dead_column(db_evidence: str) -> bool:
    """Whether the data says this column has never been written at all.

    A column the table never fills is the one case where a row would occupy the
    list without answering anything, so it is the only reason a relation is kept
    off the page. It stays counted per table so the page can offer to reveal it.

    An empty table is deliberately not the same case: the relation may well be
    real and the code dimension often still has something to say about it.
    """
    return db_evidence == "never_written"


def check_verdict(
    *,
    code_cardinality: str,
    code_evidence: str,
    db_cardinality: str,
    db_evidence: str,
) -> None:
    """Reject the pairs the database's check constraints would also reject.

    Writers go through this before they reach Postgres so a bad verdict fails
    where it was built rather than as a constraint violation several layers down.
    """
    for cardinality in (code_cardinality, db_cardinality):
        if cardinality not in STORED_CARDINALITIES:
            raise ValueError(f"基数 {cardinality!r} 只能是 {sorted(STORED_CARDINALITIES)} 之一")
    as_code_evidence(code_evidence)
    as_db_evidence(db_evidence)
    if (code_evidence in _INCONCLUSIVE_CODE) != (code_cardinality == "unknown"):
        raise ValueError(f"代码依据 {code_evidence!r} 和基数 {code_cardinality!r} 不能同时成立")
    if (db_evidence in _INCONCLUSIVE_DB) != (db_cardinality == "unknown"):
        raise ValueError(f"数据依据 {db_evidence!r} 和基数 {db_cardinality!r} 不能同时成立")
