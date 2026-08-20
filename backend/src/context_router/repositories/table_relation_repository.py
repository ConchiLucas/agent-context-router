from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any, Literal, Protocol, cast

import psycopg

from context_router.schemas.table_relations import TableRelationMeasurement

TableRelationEnvironment = str
_ENVIRONMENT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MAX_PAGE_SIZE = 500


class TableRelationRepositoryError(RuntimeError):
    def __init__(self, message: str, *, code: str = "table_relation_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TableRelationGenerationRecord:
    id: str
    workspace_id: str
    environment: TableRelationEnvironment
    status: str
    revision: int
    edge_count: int = 0
    relation_count: int = 0
    hidden_count: int = 0
    published_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TableRelationTableRecord:
    generation_id: str
    database_key: str
    schema_name: str
    table_name: str
    relation_count: int = 0
    # Dead columns, held off the list but counted so a card can reveal them.
    hidden_count: int = 0


@dataclass(frozen=True, slots=True)
class TableRelationTablePage:
    tables: tuple[TableRelationTableRecord, ...] = ()
    total_count: int = 0
    related_count: int = 0


@dataclass(frozen=True, slots=True)
class TableRelationEdgeRecord:
    """One stored relation, carrying both dimensions' verdicts.

    Both cardinalities are parent-to-child, the direction ``orientation`` picks
    out. The two dimensions are independent by design: neither is derived from
    the other, and a disagreement between them is data rather than corruption.
    """

    id: str
    generation_id: str
    left_database_key: str
    left_schema: str
    left_table: str
    left_column: str
    right_database_key: str
    right_schema: str
    right_table: str
    right_column: str
    orientation: str
    code_cardinality: str
    code_evidence: str
    db_cardinality: str
    db_evidence: str
    # The counts the data verdict was read off. Required rather than optional: a
    # verdict whose numbers went missing is one nobody can check, which is the
    # state this design exists to avoid.
    measurement: TableRelationMeasurement
    code_checked_at: datetime | None = None
    db_measured_at: datetime | None = None
    cross_database: bool = False


@dataclass(frozen=True, slots=True)
class TableRelationCodeSiteRecord:
    """One stored place in the source behind a code verdict.

    ``kind`` is the only judgement here; the role a site plays and the
    multiplicity it argues for are computed from it on read, so the two can
    never be stored in a combination that contradicts each other.
    """

    edge_id: str
    kind: str
    file_path: str
    method_name: str
    snippet: str
    position: int = 0


@dataclass(frozen=True, slots=True)
class TableRelationWriteSiteRecord:
    """One stored persist call against a table, not against a relation.

    Identity is the table's, because that is the question this answers: which
    methods write *this* table. Hanging it on an edge would make a cargo insert
    reappear under every foreign key the insert happens to fill, and under the
    parent table the edge also names.
    """

    generation_id: str
    database_key: str
    schema_name: str
    table_name: str
    kind: str
    file_path: str
    method_name: str
    snippet: str
    position: int = 0


@dataclass(frozen=True, slots=True)
class TableRelationUpdateSiteRecord:
    """One stored update call against a table, not against a relation.

    Independent of insert sites: the same method can insert and later update,
    and those two facts belong on two lists.
    """

    generation_id: str
    database_key: str
    schema_name: str
    table_name: str
    kind: str
    file_path: str
    method_name: str
    snippet: str
    position: int = 0


class TableRelationReader(Protocol):
    def get_generation(
        self,
        *,
        workspace_id: str,
        status: str,
        environment: TableRelationEnvironment | None = None,
    ) -> TableRelationGenerationRecord | None: ...

    def list_database_keys(self, generation_id: str) -> list[str]: ...

    def list_tables(
        self,
        *,
        generation_id: str,
        database_key: str | None = None,
        only_related: bool = True,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TableRelationTablePage: ...

    def get_table(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> TableRelationTableRecord | None: ...

    def list_edges_for_table(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationEdgeRecord]: ...

    def get_edge(
        self,
        *,
        generation_id: str,
        edge_id: str,
    ) -> TableRelationEdgeRecord | None: ...

    def list_code_sites(self, edge_id: str) -> list[TableRelationCodeSiteRecord]: ...

    def list_write_sites(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationWriteSiteRecord]: ...

    def list_update_sites(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationUpdateSiteRecord]: ...


class TableRelationStore(TableRelationReader, Protocol):
    pass


@dataclass(slots=True)
class _MemoryGeneration:
    generation: TableRelationGenerationRecord
    tables: list[TableRelationTableRecord] = field(default_factory=list)
    edges: list[TableRelationEdgeRecord] = field(default_factory=list)
    code_sites: list[TableRelationCodeSiteRecord] = field(default_factory=list)
    write_sites: list[TableRelationWriteSiteRecord] = field(default_factory=list)
    update_sites: list[TableRelationUpdateSiteRecord] = field(default_factory=list)


class InMemoryTableRelationRepository:
    """Read-only in-memory projection used by tests and database-less runs."""

    def __init__(self) -> None:
        self._generations: dict[str, _MemoryGeneration] = {}

    def add_generation(
        self,
        generation: TableRelationGenerationRecord,
        *,
        tables: list[TableRelationTableRecord] | None = None,
        edges: list[TableRelationEdgeRecord] | None = None,
        code_sites: list[TableRelationCodeSiteRecord] | None = None,
        write_sites: list[TableRelationWriteSiteRecord] | None = None,
        update_sites: list[TableRelationUpdateSiteRecord] | None = None,
    ) -> None:
        self._generations[generation.id] = _MemoryGeneration(
            generation=generation,
            tables=list(tables or []),
            edges=list(edges or []),
            code_sites=list(code_sites or []),
            write_sites=list(write_sites or []),
            update_sites=list(update_sites or []),
        )

    def get_generation(
        self,
        *,
        workspace_id: str,
        status: str,
        environment: TableRelationEnvironment | None = None,
    ) -> TableRelationGenerationRecord | None:
        _ensure_environment(environment)
        matches = [
            entry.generation
            for entry in self._generations.values()
            if entry.generation.workspace_id == workspace_id
            and entry.generation.status == status
            and (environment is None or entry.generation.environment == environment)
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item.revision)

    def list_database_keys(self, generation_id: str) -> list[str]:
        entry = self._generations.get(generation_id)
        if entry is None:
            return []
        return sorted({table.database_key for table in entry.tables})

    def list_tables(
        self,
        *,
        generation_id: str,
        database_key: str | None = None,
        only_related: bool = True,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TableRelationTablePage:
        entry = self._generations.get(generation_id)
        if entry is None:
            return TableRelationTablePage()
        scoped = [
            table
            for table in entry.tables
            if database_key is None or table.database_key == database_key
        ]
        needle = (search or "").strip().casefold()
        filtered = [
            table
            for table in scoped
            if (not needle or needle in table.table_name.casefold())
            and (not only_related or table.relation_count > 0)
        ]
        ordered = sorted(
            filtered,
            key=lambda item: (
                -item.relation_count,
                item.database_key.casefold(),
                item.schema_name.casefold(),
                item.table_name.casefold(),
            ),
        )
        window = _page(ordered, limit=limit, offset=offset)
        return TableRelationTablePage(
            tables=tuple(window),
            total_count=len(scoped),
            related_count=sum(1 for table in scoped if table.relation_count > 0),
        )

    def get_table(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> TableRelationTableRecord | None:
        entry = self._generations.get(generation_id)
        if entry is None:
            return None
        return next(
            (
                table
                for table in entry.tables
                if table.database_key == database_key
                and table.schema_name == schema_name
                and table.table_name == table_name
            ),
            None,
        )

    def list_edges_for_table(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationEdgeRecord]:
        entry = self._generations.get(generation_id)
        if entry is None:
            return []
        target = (database_key, schema_name, table_name)
        return [
            edge
            for edge in entry.edges
            if (edge.left_database_key, edge.left_schema, edge.left_table) == target
            or (edge.right_database_key, edge.right_schema, edge.right_table) == target
        ]

    def get_edge(
        self,
        *,
        generation_id: str,
        edge_id: str,
    ) -> TableRelationEdgeRecord | None:
        entry = self._generations.get(generation_id)
        if entry is None:
            return None
        return next((edge for edge in entry.edges if edge.id == edge_id), None)

    def list_code_sites(self, edge_id: str) -> list[TableRelationCodeSiteRecord]:
        sites = [
            site
            for entry in self._generations.values()
            for site in entry.code_sites
            if site.edge_id == edge_id
        ]
        return sorted(sites, key=lambda site: site.position)

    def list_write_sites(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationWriteSiteRecord]:
        entry = self._generations.get(generation_id)
        if entry is None:
            return []
        target = (database_key, schema_name, table_name)
        sites = [
            site
            for site in entry.write_sites
            if (site.database_key, site.schema_name, site.table_name) == target
        ]
        return sorted(sites, key=lambda site: site.position)

    def list_update_sites(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationUpdateSiteRecord]:
        entry = self._generations.get(generation_id)
        if entry is None:
            return []
        target = (database_key, schema_name, table_name)
        sites = [
            site
            for site in entry.update_sites
            if (site.database_key, site.schema_name, site.table_name) == target
        ]
        return sorted(sites, key=lambda site: site.position)


class PostgresTableRelationRepository:
    def __init__(self, database_url: str | None) -> None:
        self._database_url = database_url.strip() if database_url else None

    def get_generation(
        self,
        *,
        workspace_id: str,
        status: str,
        environment: TableRelationEnvironment | None = None,
    ) -> TableRelationGenerationRecord | None:
        _ensure_environment(environment)
        with self._session("表关联版本读取失败") as connection:
            row = connection.execute(
                _GENERATION_SELECT
                + """
                WHERE workspace_id = %s
                  AND status = %s
                  AND (%s::text IS NULL OR environment = %s)
                ORDER BY revision DESC
                LIMIT 1
                """,
                (workspace_id, status, environment, environment),
            ).fetchone()
        return _generation_record(row) if row is not None else None

    def list_database_keys(self, generation_id: str) -> list[str]:
        with self._session("表关联数据库清单读取失败") as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT database_key
                FROM workspace_table_relation_tables
                WHERE generation_id = %s
                ORDER BY database_key
                """,
                (generation_id,),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def list_tables(
        self,
        *,
        generation_id: str,
        database_key: str | None = None,
        only_related: bool = True,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> TableRelationTablePage:
        needle = (search or "").strip()
        pattern = f"%{needle}%" if needle else None
        safe_limit = _safe_limit(limit)
        safe_offset = max(0, offset)
        with self._session("表关联表清单读取失败") as connection:
            totals = connection.execute(
                """
                SELECT
                    count(*) AS total_count,
                    count(*) FILTER (WHERE relation_count > 0) AS related_count
                FROM workspace_table_relation_tables
                WHERE generation_id = %s
                  AND (%s::text IS NULL OR database_key = %s)
                """,
                (generation_id, database_key, database_key),
            ).fetchone()
            rows = connection.execute(
                _TABLE_SELECT
                + """
                WHERE generation_id = %s
                  AND (%s::text IS NULL OR database_key = %s)
                  AND (%s::text IS NULL OR table_name ILIKE %s)
                  AND (NOT %s OR relation_count > 0)
                ORDER BY relation_count DESC, database_key, schema_name, table_name
                LIMIT %s OFFSET %s
                """,
                (
                    generation_id,
                    database_key,
                    database_key,
                    pattern,
                    pattern,
                    only_related,
                    safe_limit,
                    safe_offset,
                ),
            ).fetchall()
        return TableRelationTablePage(
            tables=tuple(_table_record(row) for row in rows),
            total_count=int(totals[0]) if totals is not None else 0,
            related_count=int(totals[1]) if totals is not None else 0,
        )

    def get_table(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> TableRelationTableRecord | None:
        with self._session("表关联表读取失败") as connection:
            row = connection.execute(
                _TABLE_SELECT
                + """
                WHERE generation_id = %s
                  AND database_key = %s
                  AND schema_name = %s
                  AND table_name = %s
                """,
                (generation_id, database_key, schema_name, table_name),
            ).fetchone()
        return _table_record(row) if row is not None else None

    def list_edges_for_table(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationEdgeRecord]:
        with self._session("表关联边读取失败") as connection:
            rows = connection.execute(
                _EDGE_SELECT
                + """
                WHERE generation_id = %s
                  AND (
                        (left_database_key = %s AND left_schema = %s AND left_table = %s)
                     OR (right_database_key = %s AND right_schema = %s AND right_table = %s)
                  )
                ORDER BY id
                """,
                (
                    generation_id,
                    database_key,
                    schema_name,
                    table_name,
                    database_key,
                    schema_name,
                    table_name,
                ),
            ).fetchall()
        return [_edge_record(row) for row in rows]

    def get_edge(
        self,
        *,
        generation_id: str,
        edge_id: str,
    ) -> TableRelationEdgeRecord | None:
        with self._session("表关联边读取失败") as connection:
            row = connection.execute(
                _EDGE_SELECT
                + """
                WHERE generation_id = %s AND id = %s
                """,
                (generation_id, edge_id),
            ).fetchone()
        return _edge_record(row) if row is not None else None

    def list_code_sites(self, edge_id: str) -> list[TableRelationCodeSiteRecord]:
        with self._session("表关联代码点位读取失败") as connection:
            rows = connection.execute(
                """
                SELECT edge_id, kind, file_path, method_name, snippet, position
                FROM workspace_table_relation_code_sites
                WHERE edge_id = %s
                ORDER BY position
                """,
                (edge_id,),
            ).fetchall()
        return [_code_site_record(row) for row in rows]

    def list_write_sites(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationWriteSiteRecord]:
        with self._session("表关联写入入口读取失败") as connection:
            rows = connection.execute(
                """
                SELECT generation_id, database_key, schema_name, table_name,
                       kind, file_path, method_name, snippet, position
                FROM workspace_table_write_sites
                WHERE generation_id = %s
                  AND database_key = %s
                  AND schema_name = %s
                  AND table_name = %s
                ORDER BY position
                """,
                (generation_id, database_key, schema_name, table_name),
            ).fetchall()
        return [_write_site_record(row) for row in rows]

    def list_update_sites(
        self,
        *,
        generation_id: str,
        database_key: str,
        schema_name: str,
        table_name: str,
    ) -> list[TableRelationUpdateSiteRecord]:
        with self._session("表关联更新入口读取失败") as connection:
            rows = connection.execute(
                """
                SELECT generation_id, database_key, schema_name, table_name,
                       kind, file_path, method_name, snippet, position
                FROM workspace_table_update_sites
                WHERE generation_id = %s
                  AND database_key = %s
                  AND schema_name = %s
                  AND table_name = %s
                ORDER BY position
                """,
                (generation_id, database_key, schema_name, table_name),
            ).fetchall()
        return [_update_site_record(row) for row in rows]

    @contextmanager
    def _session(self, failure_message: str) -> Iterator[psycopg.Connection[Any]]:
        if not self._database_url:
            raise TableRelationRepositoryError(
                "表关联数据库尚未配置",
                code="table_relation_unavailable",
            )
        try:
            with psycopg.connect(self._database_url) as connection:
                yield connection
        except psycopg.Error as exc:
            raise TableRelationRepositoryError(failure_message) from exc


_GENERATION_SELECT = """
SELECT
    id,
    workspace_id,
    environment,
    status,
    revision,
    edge_count,
    relation_count,
    hidden_count,
    published_at
FROM workspace_table_relation_generations
"""

_TABLE_SELECT = """
SELECT
    generation_id,
    database_key,
    schema_name,
    table_name,
    relation_count,
    hidden_count
FROM workspace_table_relation_tables
"""

_EDGE_FIELDS: tuple[str, ...] = (
    "id",
    "generation_id",
    "left_database_key",
    "left_schema",
    "left_table",
    "left_column",
    "right_database_key",
    "right_schema",
    "right_table",
    "right_column",
    "orientation",
    "code_cardinality",
    "code_evidence",
    "db_cardinality",
    "db_evidence",
    "code_checked_at",
    "db_measured_at",
    "child_key_kind",
    "parent_key_kind",
    "child_table_rows",
    "child_rows_with_value",
    "child_distinct_keys",
    "parent_rows_with_value",
    "parent_distinct_keys",
    "orphan_keys",
    "cross_database",
)

_EDGE_SELECT = "SELECT " + ", ".join(_EDGE_FIELDS) + " FROM workspace_table_relation_edges "


def _ensure_environment(environment: str | None) -> None:
    if environment is not None and not _ENVIRONMENT_PATTERN.fullmatch(environment):
        raise TableRelationRepositoryError("表关联环境标识格式不正确")


def _safe_limit(limit: int) -> int:
    return max(1, min(limit, _MAX_PAGE_SIZE))


def _page[T](items: list[T], *, limit: int, offset: int) -> list[T]:
    start = max(0, offset)
    return items[start : start + _safe_limit(limit)]


def _generation_record(row: tuple[object, ...]) -> TableRelationGenerationRecord:
    return TableRelationGenerationRecord(
        id=str(row[0]),
        workspace_id=str(row[1]),
        environment=cast(TableRelationEnvironment, str(row[2])),
        status=str(row[3]),
        revision=int(cast(int, row[4])),
        edge_count=int(cast(int, row[5])),
        relation_count=int(cast(int, row[6])),
        hidden_count=int(cast(int, row[7])),
        published_at=cast(datetime | None, row[8]),
    )


def _table_record(row: tuple[object, ...]) -> TableRelationTableRecord:
    return TableRelationTableRecord(
        generation_id=str(row[0]),
        database_key=str(row[1]),
        schema_name=str(row[2]),
        table_name=str(row[3]),
        relation_count=int(cast(int, row[4])),
        hidden_count=int(cast(int, row[5])),
    )


def _code_site_record(row: tuple[object, ...]) -> TableRelationCodeSiteRecord:
    return TableRelationCodeSiteRecord(
        edge_id=str(row[0]),
        kind=str(row[1]),
        file_path=str(row[2]),
        method_name=str(row[3]),
        snippet=str(row[4]),
        position=int(cast(int, row[5])),
    )


def _write_site_record(row: tuple[object, ...]) -> TableRelationWriteSiteRecord:
    return TableRelationWriteSiteRecord(
        generation_id=str(row[0]),
        database_key=str(row[1]),
        schema_name=str(row[2]),
        table_name=str(row[3]),
        kind=str(row[4]),
        file_path=str(row[5]),
        method_name=str(row[6]),
        snippet=str(row[7]),
        position=int(cast(int, row[8])),
    )


def _update_site_record(row: tuple[object, ...]) -> TableRelationUpdateSiteRecord:
    return TableRelationUpdateSiteRecord(
        generation_id=str(row[0]),
        database_key=str(row[1]),
        schema_name=str(row[2]),
        table_name=str(row[3]),
        kind=str(row[4]),
        file_path=str(row[5]),
        method_name=str(row[6]),
        snippet=str(row[7]),
        position=int(cast(int, row[8])),
    )


def _edge_record(row: tuple[object, ...]) -> TableRelationEdgeRecord:
    # Mapped by name rather than by position: an edge now selects two dozen
    # columns, and a positional read of that many is one inserted column away
    # from silently assigning a count to the wrong field. ``strict`` makes a
    # SELECT list that drifts out of step with the fields fail here instead.
    values = dict(zip(_EDGE_FIELDS, row, strict=True))
    return TableRelationEdgeRecord(
        id=str(values["id"]),
        generation_id=str(values["generation_id"]),
        left_database_key=str(values["left_database_key"]),
        left_schema=str(values["left_schema"]),
        left_table=str(values["left_table"]),
        left_column=str(values["left_column"]),
        right_database_key=str(values["right_database_key"]),
        right_schema=str(values["right_schema"]),
        right_table=str(values["right_table"]),
        right_column=str(values["right_column"]),
        orientation=str(values["orientation"]),
        code_cardinality=str(values["code_cardinality"]),
        code_evidence=str(values["code_evidence"]),
        db_cardinality=str(values["db_cardinality"]),
        db_evidence=str(values["db_evidence"]),
        measurement=TableRelationMeasurement(
            child_key_kind=cast(Any, str(values["child_key_kind"])),
            parent_key_kind=cast(Any, str(values["parent_key_kind"])),
            child_table_rows=int(cast(int, values["child_table_rows"])),
            child_rows_with_value=int(cast(int, values["child_rows_with_value"])),
            child_distinct_keys=int(cast(int, values["child_distinct_keys"])),
            parent_rows_with_value=int(cast(int, values["parent_rows_with_value"])),
            parent_distinct_keys=int(cast(int, values["parent_distinct_keys"])),
            orphan_keys=int(cast(int, values["orphan_keys"])),
        ),
        code_checked_at=cast(datetime | None, values["code_checked_at"]),
        db_measured_at=cast(datetime | None, values["db_measured_at"]),
        cross_database=bool(values["cross_database"]),
    )
