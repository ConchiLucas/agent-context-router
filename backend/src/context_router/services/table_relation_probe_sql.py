"""The queries a stored data verdict was read off, rebuilt from its endpoints.

A detail view has to be able to hand back the query behind every number it shows,
because that is what separates a verdict a reader can contradict from one they can
only accept. These are those queries.

They are derived on read rather than saved next to the counts. A saved query
string would go on describing whatever the endpoints were called when it was
written, and the first rename would leave a relation displaying a probe of two
columns that no longer exist. Derived, a probe cannot disagree with the relation
it belongs to.

Two conventions of the databases being probed are baked in, and both are recorded
here rather than assumed silently:

* Rows are retired by setting ``deleted``, so every count filters it out. This is
  not a guess about what ought to be counted -- it is what the stored counts were
  taken with, and leaving it out would print a query that returns other numbers.
* An unset key is ``0`` in a numeric column and ``''`` in a text one, which is why
  the measurement carries the kind of each key.
"""

from __future__ import annotations

import re

from context_router.schemas.table_relations import (
    TableRelationEndpoint,
    TableRelationKeyKind,
)

# Identifiers reach these queries from stored rows and leave again as text a
# reader is invited to copy and run. Anything that would need quoting to be safe
# is refused rather than quoted: none of these databases has such a name, so a
# name that needs it is a sign something is wrong further upstream.
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

_SOFT_DELETE_COLUMN = "deleted"


class TableRelationProbeError(ValueError):
    pass


def cardinality_sql(child: TableRelationEndpoint, *, key_kind: TableRelationKeyKind) -> str:
    """How many rows carry this key, and how many distinct keys they carry.

    The whole data verdict is these two numbers compared: equal means each parent
    key occurs once, fewer distinct keys than rows means one of them recurs.
    ``table_rows`` is what tells a dead column apart from an empty table.
    """
    table = _table(child)
    column = _column(child)
    unset = _unset_value(key_kind)
    return "\n".join(
        (
            "SELECT COUNT(*) AS table_rows,",
            f"       COUNT(NULLIF({column}, {unset})) AS rows_with_value,",
            f"       COUNT(DISTINCT NULLIF({column}, {unset})) AS distinct_keys",
            f"FROM {table}",
            f"WHERE {_SOFT_DELETE_COLUMN} = 0;",
        )
    )


def parent_uniqueness_sql(parent: TableRelationEndpoint, *, key_kind: TableRelationKeyKind) -> str:
    """Whether the key being pointed at occurs at most once in the parent table.

    The precondition under everything else: if the parent key repeats, several
    children per key say nothing about the relation's shape.
    """
    table = _table(parent)
    column = _column(parent)
    unset = _unset_value(key_kind)
    return "\n".join(
        (
            f"SELECT COUNT(NULLIF({column}, {unset})) AS rows_with_value,",
            f"       COUNT(DISTINCT NULLIF({column}, {unset})) AS distinct_keys",
            f"FROM {table}",
            f"WHERE {_SOFT_DELETE_COLUMN} = 0;",
        )
    )


def orphan_sql(
    child: TableRelationEndpoint,
    parent: TableRelationEndpoint,
    *,
    key_kind: TableRelationKeyKind,
) -> str:
    """Child keys with no surviving parent row.

    Neither dimension can answer this. The code cannot see it, and the cardinality
    probe counts keys without ever asking whether they resolve to anything, so a
    column can measure a clean one-to-one while half its keys point nowhere.

    A key counted here either has no parent row at all or has one that was
    soft-deleted from under it. The query does not tell those apart, and the
    difference matters less than the fact that a join will drop the row either way.
    """
    child_table = _table(child)
    parent_table = _table(parent)
    child_column = _column(child)
    parent_column = _column(parent)
    unset = _unset_value(key_kind)
    return "\n".join(
        (
            f"SELECT COUNT(DISTINCT child.{child_column}) AS orphan_keys",
            f"FROM {child_table} AS child",
            f"LEFT JOIN {parent_table} AS parent",
            f"       ON parent.{parent_column} = child.{child_column}",
            f"      AND parent.{_SOFT_DELETE_COLUMN} = 0",
            f"WHERE child.{_SOFT_DELETE_COLUMN} = 0",
            f"  AND NULLIF(child.{child_column}, {unset}) IS NOT NULL",
            f"  AND parent.{parent_column} IS NULL;",
        )
    )


def key_kind_sql(child: TableRelationEndpoint, parent: TableRelationEndpoint) -> str:
    """The declared type of each end, for the one check that reads the schema."""
    return "\n".join(
        (
            f"SHOW COLUMNS FROM {_table(child)} LIKE '{_column(child)}';",
            f"SHOW COLUMNS FROM {_table(parent)} LIKE '{_column(parent)}';",
        )
    )


def _unset_value(key_kind: TableRelationKeyKind) -> str:
    return "0" if key_kind == "numeric" else "''"


def _table(endpoint: TableRelationEndpoint) -> str:
    """The table as the probe names it: schema-qualified, so it runs anywhere.

    The database alias is left out on purpose. It is this application's name for a
    connection and would not be understood by whatever the reader pastes into.
    """
    return f"{_safe(endpoint.schema_name)}.{_safe(endpoint.table_name)}"


def _column(endpoint: TableRelationEndpoint) -> str:
    if not endpoint.column_name:
        raise TableRelationProbeError("端点没有列名，无法生成探测 SQL")
    return _safe(endpoint.column_name)


def _safe(identifier: str) -> str:
    if not _IDENTIFIER.match(identifier):
        raise TableRelationProbeError(f"标识符 {identifier!r} 不能安全地写进探测 SQL")
    return identifier
