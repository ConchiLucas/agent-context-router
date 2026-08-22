"""Read-only projection of stored table relations.

The stored edge is direction-neutral: endpoints are persisted as a canonical
ordered pair and ``orientation`` records which endpoint owns the primary key.
Both cardinalities are stored parent-to-child. This service re-expresses each
edge from the perspective of the table being inspected, which means flipping
``one_to_many`` into ``many_to_one`` whenever the inspected table is the side that
holds the foreign key. The flip applies to each dimension on its own, so two
verdicts that disagreed in storage still disagree in the same way on the page.

What does *not* move with the perspective is the pair of endpoints. A relation is
named after its foreign key side, so ``sys_user_ext.user_id`` identifies the same
relation whether you arrived from ``sys_user`` or from ``sys_user_ext``, and only
the cardinalities differ between the two visits. A column pointing at its own
table is the one case where both perspectives coincide, and it is stated once.

Dead columns are dropped here rather than in the client. The table counters are
stored per table, so filtering in one place is the only way the counts and the
rendered rows can agree; ``project_table_counters`` lives here for the same
reason, going through the very view builder the list goes through.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from context_router.repositories.table_relation_repository import (
    TableRelationCodeSiteRecord,
    TableRelationEdgeRecord,
    TableRelationGenerationRecord,
    TableRelationReader,
    TableRelationTableRecord,
    TableRelationUpdateSiteRecord,
    TableRelationWriteSiteRecord,
)
from context_router.schemas.table_relations import (
    TableRelationCardinality,
    TableRelationCheck,
    TableRelationCheckOutcome,
    TableRelationCodeSite,
    TableRelationDetail,
    TableRelationDirection,
    TableRelationEndpoint,
    TableRelationGenerationStatus,
    TableRelationGenerationSummary,
    TableRelationMeasurement,
    TableRelationStatus,
    TableRelationTableDetail,
    TableRelationTableIdentity,
    TableRelationTableList,
    TableRelationTableSummary,
    TableRelationTableUpdates,
    TableRelationTableWrites,
    TableRelationUpdateSite,
    TableRelationView,
    TableRelationWriteSite,
)
from context_router.services.table_relation_probe_sql import (
    cardinality_sql,
    key_kind_sql,
    orphan_sql,
    parent_uniqueness_sql,
)
from context_router.services.table_relation_rules import (
    as_cardinality,
    as_code_evidence,
    as_db_evidence,
    as_site_kind,
    as_update_kind,
    as_write_kind,
    flip_cardinality,
    is_dead_column,
    site_implication,
    site_role,
)

_REBUILD_COMMAND_TEMPLATE = (
    "docker compose exec backend uv run python -m"
    " context_router.scripts.seed_table_relations --workspace {workspace_id}"
)


class TableRelationNotFoundError(LookupError):
    def __init__(self, message: str, *, code: str = "table_relation_not_found") -> None:
        super().__init__(message)
        self.code = code


_TableIdentity = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class TableRelationCounters:
    """How many rows one table draws, and how many it holds back."""

    relation_count: int = 0
    hidden_count: int = 0


@dataclass(frozen=True, slots=True)
class _Side:
    database_key: str
    schema_name: str
    table_name: str
    column_name: str

    @property
    def table(self) -> _TableIdentity:
        return (self.database_key, self.schema_name, self.table_name)

    def endpoint(self) -> TableRelationEndpoint:
        return TableRelationEndpoint(
            database_key=self.database_key,
            schema_name=self.schema_name,
            table_name=self.table_name,
            column_name=self.column_name,
        )

    def reference(self, *, qualified: bool) -> str:
        """The endpoint written the way a row prints it.

        The database alias is only spelled out when the relation spans two
        databases, where the table name alone would be ambiguous.
        """
        prefix = f"{self.database_key}." if qualified else ""
        return f"{prefix}{self.table_name}.{self.column_name}"


class TableRelationQueryService:
    def __init__(self, *, reader: TableRelationReader) -> None:
        self._reader = reader

    def get_status(
        self,
        workspace_id: str,
    ) -> TableRelationStatus:
        published = self._published(workspace_id)
        building = self._reader.get_generation(
            workspace_id=workspace_id,
            status="building",
        )
        database_keys = (
            self._reader.list_database_keys(published.id) if published is not None else []
        )
        return TableRelationStatus(
            workspace_id=workspace_id,
            generation=_generation_summary(published),
            building=_generation_summary(building),
            database_keys=database_keys,
            rebuild_command=_REBUILD_COMMAND_TEMPLATE.format(workspace_id=workspace_id),
        )

    def list_tables(
        self,
        workspace_id: str,
        *,
        database_key: str | None = None,
        only_related: bool = True,
        search: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> TableRelationTableList:
        published = self._published(workspace_id)
        if published is None:
            return TableRelationTableList(workspace_id=workspace_id, only_related=only_related)
        page = self._reader.list_tables(
            generation_id=published.id,
            database_key=database_key,
            only_related=only_related,
            search=search,
            limit=limit,
            offset=offset,
        )
        return TableRelationTableList(
            workspace_id=workspace_id,
            generation=_generation_summary(published),
            only_related=only_related,
            total_count=page.total_count,
            related_count=page.related_count,
            returned_count=len(page.tables),
            tables=[_table_summary(table) for table in page.tables],
        )

    def get_table_detail(
        self,
        workspace_id: str,
        *,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> TableRelationTableDetail:
        published = self._published(workspace_id)
        if published is None:
            raise TableRelationNotFoundError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        table = self._reader.get_table(
            generation_id=published.id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
        )
        if table is None:
            raise TableRelationNotFoundError("表关联数据里没有这张表")
        target = (database_key, schema_name, table_name)
        relations: list[TableRelationView] = []
        hidden_count = 0
        for edge in self._reader.list_edges_for_table(
            generation_id=published.id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
        ):
            view = _edge_view(edge, target)
            if view is None:
                continue
            if is_dead_column(edge.db_evidence):
                hidden_count += 1
                continue
            relations.append(view)
        relations.sort(key=_view_sort_key)
        return TableRelationTableDetail(
            workspace_id=workspace_id,
            generation=_require_summary(published),
            table=TableRelationTableIdentity(
                database_key=table.database_key,
                schema_name=table.schema_name,
                table_name=table.table_name,
            ),
            relations=relations,
            relation_count=len(relations),
            hidden_count=hidden_count,
        )

    def get_table_writes(
        self,
        workspace_id: str,
        *,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> TableRelationTableWrites:
        """The persist calls recorded against this table, not against its edges.

        Fetched separately from the table's relation list for the same reason
        relation evidence is: most tables are never opened this far, and folding
        the snippets into the list payload would make every table pay for them.
        """
        published = self._published(workspace_id)
        if published is None:
            raise TableRelationNotFoundError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        table = self._reader.get_table(
            generation_id=published.id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
        )
        if table is None:
            raise TableRelationNotFoundError("表关联数据里没有这张表")
        return TableRelationTableWrites(
            workspace_id=workspace_id,
            generation=_require_summary(published),
            table=TableRelationTableIdentity(
                database_key=table.database_key,
                schema_name=table.schema_name,
                table_name=table.table_name,
            ),
            writes=[
                _write_site(site)
                for site in self._reader.list_write_sites(
                    generation_id=published.id,
                    database_key=database_key,
                    schema_name=schema_name,
                    table_name=table_name,
                )
            ],
        )

    def get_table_updates(
        self,
        workspace_id: str,
        *,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> TableRelationTableUpdates:
        """The update calls recorded against this table, not against its edges."""
        published = self._published(workspace_id)
        if published is None:
            raise TableRelationNotFoundError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        table = self._reader.get_table(
            generation_id=published.id,
            database_key=database_key,
            schema_name=schema_name,
            table_name=table_name,
        )
        if table is None:
            raise TableRelationNotFoundError("表关联数据里没有这张表")
        return TableRelationTableUpdates(
            workspace_id=workspace_id,
            generation=_require_summary(published),
            table=TableRelationTableIdentity(
                database_key=table.database_key,
                schema_name=table.schema_name,
                table_name=table.table_name,
            ),
            updates=[
                _update_site(site)
                for site in self._reader.list_update_sites(
                    generation_id=published.id,
                    database_key=database_key,
                    schema_name=schema_name,
                    table_name=table_name,
                )
            ],
        )

    def get_relation_detail(
        self,
        workspace_id: str,
        *,
        database_key: str,
        schema_name: str,
        table_name: str,
        edge_id: str,
    ) -> TableRelationDetail:
        """One relation with the evidence behind its data verdict.

        The table is part of the request rather than looked up from the edge,
        because the two cardinalities are stated from an end and the detail has to
        state them from the same end the row did. Going through ``_edge_view`` is
        what makes that true by construction instead of by agreement.

        A dead column is served here even though the list hides it: hiding it there
        is about not filling a list with rows that answer nothing, and this is the
        one place where "the table has rows and this column has none" is the answer.
        """
        published = self._published(workspace_id)
        if published is None:
            raise TableRelationNotFoundError(
                "这个工作空间还没有已发布的表关联数据",
                code="table_relation_generation_missing",
            )
        edge = self._reader.get_edge(generation_id=published.id, edge_id=edge_id)
        if edge is None:
            raise TableRelationNotFoundError("表关联数据里没有这条关系")
        view = _edge_view(edge, (database_key, schema_name, table_name))
        if view is None:
            raise TableRelationNotFoundError("这条关系不在这张表上")
        return TableRelationDetail(
            workspace_id=workspace_id,
            generation=_require_summary(published),
            table=TableRelationTableIdentity(
                database_key=database_key,
                schema_name=schema_name,
                table_name=table_name,
            ),
            relation=view,
            measurement=edge.measurement,
            checks=_checks(view, edge.measurement),
            code_sites=[
                _code_site(site, flip=view.direction == "outbound")
                for site in self._reader.list_code_sites(edge.id)
            ],
        )

    def _published(
        self,
        workspace_id: str,
    ) -> TableRelationGenerationRecord | None:
        return self._reader.get_generation(
            workspace_id=workspace_id,
            status="published",
        )


def _left_side(edge: TableRelationEdgeRecord) -> _Side:
    return _Side(
        database_key=edge.left_database_key,
        schema_name=edge.left_schema,
        table_name=edge.left_table,
        column_name=edge.left_column,
    )


def _right_side(edge: TableRelationEdgeRecord) -> _Side:
    return _Side(
        database_key=edge.right_database_key,
        schema_name=edge.right_schema,
        table_name=edge.right_table,
        column_name=edge.right_column,
    )


def _parent_and_child(edge: TableRelationEdgeRecord) -> tuple[_Side, _Side] | None:
    """Resolve which endpoint owns the key and which one references it."""
    if edge.orientation == "left_to_right":
        return _left_side(edge), _right_side(edge)
    if edge.orientation == "right_to_left":
        return _right_side(edge), _left_side(edge)
    return None


def _edge_view(
    edge: TableRelationEdgeRecord,
    target: _TableIdentity,
) -> TableRelationView | None:
    """Express one edge as the single row the inspected table draws for it.

    Direction decides only whether the stored cardinalities are flipped. A
    self-referencing column is both ends at once, so neither reading is more
    correct than the other and the stored parent-to-child one is kept: "one menu
    has many children" is the statement worth making about ``parent_id``.
    """
    sides = _parent_and_child(edge)
    if sides is None:
        return None
    parent, child = sides
    is_parent = parent.table == target
    is_child = child.table == target
    if not is_parent and not is_child:
        return None
    direction: TableRelationDirection
    if is_parent and is_child:
        direction = "self"
    elif is_child:
        direction = "outbound"
    else:
        direction = "inbound"
    flip = direction == "outbound"
    return TableRelationView(
        edge_id=edge.id,
        relation_id=child.reference(qualified=edge.cross_database),
        references=parent.reference(qualified=edge.cross_database),
        child=child.endpoint(),
        parent=parent.endpoint(),
        direction=direction,
        code_cardinality=_read(edge.code_cardinality, flip=flip),
        code_evidence=as_code_evidence(edge.code_evidence),
        db_cardinality=_read(edge.db_cardinality, flip=flip),
        db_evidence=as_db_evidence(edge.db_evidence),
        code_checked_at=edge.code_checked_at,
        db_measured_at=edge.db_measured_at,
        cross_database=edge.cross_database,
    )


def _read(cardinality: str, *, flip: bool) -> TableRelationCardinality:
    return flip_cardinality(cardinality) if flip else as_cardinality(cardinality)


def _code_site(site: TableRelationCodeSiteRecord, *, flip: bool) -> TableRelationCodeSite:
    """One stored site, re-expressed from the same end the verdict is stated from.

    What a site argues for is flipped along with the verdict it supports. Left
    unflipped it would read as ``one_to_many`` beneath a verdict reading
    ``many_to_one`` and look like the contradiction it is not -- both being the
    same claim, seen from the two ends.
    """
    return TableRelationCodeSite(
        kind=as_site_kind(site.kind),
        role=site_role(site.kind),
        implies=_read(site_implication(site.kind), flip=flip),
        file_path=site.file_path,
        method_name=site.method_name,
        snippet=site.snippet,
    )


def _write_site(site: TableRelationWriteSiteRecord) -> TableRelationWriteSite:
    return TableRelationWriteSite(
        kind=as_write_kind(site.kind),
        file_path=site.file_path,
        method_name=site.method_name,
        snippet=site.snippet,
    )


def _update_site(site: TableRelationUpdateSiteRecord) -> TableRelationUpdateSite:
    return TableRelationUpdateSite(
        kind=as_update_kind(site.kind),
        file_path=site.file_path,
        method_name=site.method_name,
        snippet=site.snippet,
    )


def _checks(
    view: TableRelationView,
    measurement: TableRelationMeasurement,
) -> list[TableRelationCheck]:
    """Everything that was looked at, each with the query that looks again.

    The first three always appear, including when they came back inconclusive: a
    check that quietly disappears when it has nothing to report is indistinguishable
    from one that was never run. The fourth is different -- key kinds match on
    essentially every relation, so a row saying so on every relation would be noise,
    and it is stated only when it is a finding.
    """
    child = view.child
    parent = view.parent
    checks = [
        TableRelationCheck(
            key="cardinality",
            # Only a full measurement confirms anything. Too few rows, a column
            # nobody writes, and an empty table are three different reasons the
            # question could not be answered, and the evidence already names which.
            outcome="confirmed" if view.db_evidence == "measured" else "inconclusive",
            sql=cardinality_sql(child, key_kind=measurement.child_key_kind),
        ),
        TableRelationCheck(
            key="parent_unique",
            outcome=_parent_unique_outcome(measurement),
            sql=parent_uniqueness_sql(parent, key_kind=measurement.parent_key_kind),
        ),
        TableRelationCheck(
            key="orphan",
            outcome=_orphan_outcome(measurement),
            sql=orphan_sql(child, parent, key_kind=measurement.child_key_kind),
        ),
    ]
    if not measurement.keys_comparable:
        checks.append(
            TableRelationCheck(
                key="key_kind",
                outcome="attention",
                sql=key_kind_sql(child, parent),
            )
        )
    return checks


def _parent_unique_outcome(measurement: TableRelationMeasurement) -> TableRelationCheckOutcome:
    if measurement.parent_rows_with_value == 0:
        return "inconclusive"
    return "confirmed" if measurement.parent_keys_unique else "attention"


def _orphan_outcome(measurement: TableRelationMeasurement) -> TableRelationCheckOutcome:
    if measurement.child_distinct_keys == 0:
        return "inconclusive"
    return "attention" if measurement.orphan_keys > 0 else "confirmed"


def project_table_counters(
    *,
    edges: Sequence[TableRelationEdgeRecord],
) -> dict[_TableIdentity, TableRelationCounters]:
    """Count every table's rows in one pass, for the writer to persist.

    The table list is paged, so it cannot re-derive these numbers from the edges.
    Deriving them here, through the same ``_edge_view`` the list goes through, is
    what keeps a table card from advertising a row the page will not draw.

    Tables that ended up with no relation at all are absent from the result
    rather than present with zeros; the caller knows its own table list.
    """
    relations: dict[_TableIdentity, int] = defaultdict(int)
    hidden: dict[_TableIdentity, int] = defaultdict(int)
    for edge in edges:
        sides = _parent_and_child(edge)
        if sides is None:
            continue
        dead = is_dead_column(edge.db_evidence)
        # A self-referencing column draws one row, not one per end.
        for identity in {sides[0].table, sides[1].table}:
            if dead:
                hidden[identity] += 1
            else:
                relations[identity] += 1
    return {
        identity: TableRelationCounters(
            relation_count=relations.get(identity, 0),
            hidden_count=hidden.get(identity, 0),
        )
        for identity in relations.keys() | hidden.keys()
    }


def _view_sort_key(view: TableRelationView) -> tuple[str, str, str, str]:
    """Ordered by the relation's own identity, which no perspective can change.

    Built only from the endpoints, so a rebuild that changes nothing but a
    verdict cannot move a row out from under the cursor.
    """
    return (
        _table_key(view.child),
        (view.child.column_name or "").casefold(),
        _table_key(view.parent),
        (view.parent.column_name or "").casefold(),
    )


def _table_key(endpoint: TableRelationEndpoint) -> str:
    return ".".join(
        (
            endpoint.database_key.casefold(),
            endpoint.schema_name.casefold(),
            endpoint.table_name.casefold(),
        )
    )


def _generation_summary(
    record: TableRelationGenerationRecord | None,
) -> TableRelationGenerationSummary | None:
    return None if record is None else _require_summary(record)


def _require_summary(
    record: TableRelationGenerationRecord,
) -> TableRelationGenerationSummary:
    return TableRelationGenerationSummary(
        generation_id=record.id,
        revision=record.revision,
        environment=record.environment,
        status=_generation_status(record.status),
        edge_count=record.edge_count,
        relation_count=record.relation_count,
        hidden_count=record.hidden_count,
        published_at=record.published_at,
    )


def _table_summary(record: TableRelationTableRecord) -> TableRelationTableSummary:
    return TableRelationTableSummary(
        database_key=record.database_key,
        schema_name=record.schema_name,
        table_name=record.table_name,
        relation_count=record.relation_count,
        hidden_count=record.hidden_count,
    )


def _generation_status(value: str) -> TableRelationGenerationStatus:
    allowed = {"building", "published", "superseded", "failed"}
    return value if value in allowed else "failed"  # type: ignore[return-value]
