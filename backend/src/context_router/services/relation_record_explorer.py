from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from context_router.database.errors import DatabaseAccessError, DatabaseConnectorError
from context_router.database.manager import ConnectorManager, ConnectorManagerError
from context_router.database.models import DatabaseObjectType, SearchDetail, SearchObjectsRequest
from context_router.database.policy import (
    QueryPolicyError,
    SqlSafetyPolicy,
    policy_as_safety_context,
)
from context_router.database.result import DatabaseResultFormatter, ResultFormattingError
from context_router.schemas.relation_records import (
    RelationRecordCard,
    RelationRecordColumn,
    RelationRecordPage,
    RelationRecordSearchInput,
    RelationRecordSearchResult,
    RelationRecordTable,
)
from context_router.schemas.table_relations import TableRelationEndpoint, TableRelationView
from context_router.services.database_access import DatabaseAccessService, ResolvedDatabaseAccess
from context_router.services.table_relation_query import TableRelationQueryService

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")
_MAX_MATCHED_KEYS = 500
_MAX_RELATED_TABLES = 40
_PAGE_SIZE = 3
_ONE_TO_ONE_LIMIT = 20


class RelationRecordExplorerError(RuntimeError):
    def __init__(self, message: str, *, code: str = "relation_record_query_failed") -> None:
        super().__init__(message)
        self.code = code


class RelationRecordExplorerService:
    """Explore direct related rows using only identifiers from the published graph."""

    def __init__(
        self,
        *,
        relation_query: TableRelationQueryService,
        database_access: DatabaseAccessService,
        connector_manager: ConnectorManager,
        result_formatter: DatabaseResultFormatter,
    ) -> None:
        self._relations = relation_query
        self._database_access = database_access
        self._connector_manager = connector_manager
        self._result_formatter = result_formatter
        self._sql_policy = SqlSafetyPolicy()

    def search(
        self,
        *,
        workspace_id: str,
        request: RelationRecordSearchInput,
    ) -> RelationRecordSearchResult:
        identity = request.table
        detail = self._relations.get_table_detail(
            workspace_id,
            environment=request.environment,
            database_key=identity.database_key,
            schema_name=identity.schema_name,
            table_name=identity.table_name,
        )
        relations = detail.relations
        if request.edge_id is not None:
            relations = [item for item in relations if item.edge_id == request.edge_id]
            if not relations:
                raise RelationRecordExplorerError(
                    "当前表没有这条关联关系",
                    code="relation_not_found",
                )

        source_access = self._resolve(
            workspace_id, request.environment, identity.database_key, require_query=True
        )
        prepared: list[tuple[TableRelationView, TableRelationEndpoint, TableRelationEndpoint]] = []
        scanned_columns: list[str] = []

        for relation in relations:
            source, target = _endpoints_for_table(relation, identity)
            if source.column_name is None or target.column_name is None:
                continue
            if source.column_name not in scanned_columns:
                scanned_columns.append(source.column_name)
            prepared.append((relation, source, target))

        key_cache, keys_truncated = self._matching_keys_by_column(
            source_access,
            [item[1] for item in prepared],
            request.keyword,
        )
        matched = [
            item
            for item in prepared
            if key_cache.get(item[1].column_name or "") or request.edge_id is not None
        ][:_MAX_RELATED_TABLES]
        with ThreadPoolExecutor(max_workers=min(4, max(len(matched), 1))) as executor:
            futures = [
                executor.submit(
                    self._card,
                    workspace_id=workspace_id,
                    environment=request.environment,
                    relation=relation,
                    source=source,
                    target=target,
                    keys=key_cache.get(source.column_name or "", []),
                    keys_truncated=keys_truncated,
                    requested_page=request.page,
                )
                for relation, source, target in matched
            ]
            cards = [future.result() for future in futures]

        return RelationRecordSearchResult(
            workspace_id=workspace_id,
            environment=request.environment,
            table=identity,
            keyword=request.keyword,
            scanned_columns=scanned_columns,
            cards=cards,
        )

    def _card(
        self,
        *,
        workspace_id: str,
        environment: str,
        relation: TableRelationView,
        source: TableRelationEndpoint,
        target: TableRelationEndpoint,
        keys: list[Any],
        keys_truncated: bool,
        requested_page: int,
    ) -> RelationRecordCard:
        target_access = self._resolve(
            workspace_id, environment, target.database_key, require_query=True
        )
        columns = self._columns(target_access, target)
        if not keys:
            return _empty_card(relation, source, target, columns)

        target_column = _quote(target.column_name, target_access.policy.engine)
        key_literals = ", ".join(_literal(item, target_access.policy.engine) for item in keys)
        where = f"{target_column} IN ({key_literals})"
        table_sql = _table_reference(target, target_access)
        count_result = self._execute(
            target_access,
            f"SELECT COUNT(*) AS total_rows FROM {table_sql} WHERE {where}",
        )
        total_rows = int(next(iter(count_result.rows), (0,))[0])
        paged = relation.db_cardinality != "one_to_one"
        total_pages = (
            math.ceil(total_rows / _PAGE_SIZE) if paged and total_rows else (1 if total_rows else 0)
        )
        page = min(requested_page, max(total_pages, 1))
        limit = _PAGE_SIZE if paged else min(max(total_rows, 1), _ONE_TO_ONE_LIMIT)
        offset = (page - 1) * _PAGE_SIZE if paged else 0
        order = _quote(target.column_name, target_access.policy.engine)
        result = self._execute(
            target_access,
            (
                f"SELECT * FROM {table_sql} WHERE {where} "
                f"ORDER BY {order} LIMIT {limit} OFFSET {offset}"
            ),
        )
        formatted = self._result_formatter.format_query(result, target_access.policy)
        query_columns = [str(item["name"]) for item in formatted.as_dict()["columns"]]
        metadata = {item.name: item for item in columns}
        rendered_columns = [
            RelationRecordColumn(
                name=name,
                type=metadata.get(name).type if name in metadata else "",
                comment=metadata.get(name).comment if name in metadata else "",
                relation_key=name == target.column_name,
            )
            for name in query_columns
        ]
        warning = None
        if keys_truncated:
            warning = f"匹配键超过 {_MAX_MATCHED_KEYS} 个，仅查询前 {_MAX_MATCHED_KEYS} 个"
        elif not paged and total_rows > _ONE_TO_ONE_LIMIT:
            warning = f"1:1 关系不分页，仅展示前 {_ONE_TO_ONE_LIMIT} 条"
        return RelationRecordCard(
            edge_id=relation.edge_id,
            relation_id=relation.relation_id,
            cardinality=relation.db_cardinality,
            source_column=source.column_name,
            target=RelationRecordTable(
                database_key=target.database_key,
                schema_name=target.schema_name,
                table_name=target.table_name,
            ),
            target_column=target.column_name,
            columns=rendered_columns,
            rows=formatted.as_dict()["rows"],
            page=RelationRecordPage(
                page=page,
                page_size=_PAGE_SIZE,
                total_rows=total_rows,
                total_pages=total_pages,
            ),
            matched_key_count=len(keys),
            matched_keys_truncated=keys_truncated,
            warning=warning,
        )

    def _matching_keys_by_column(
        self,
        access: ResolvedDatabaseAccess,
        endpoints: list[TableRelationEndpoint],
        keyword: str,
    ) -> tuple[dict[str, list[Any]], bool]:
        unique: dict[str, TableRelationEndpoint] = {}
        for endpoint in endpoints:
            if endpoint.column_name:
                unique.setdefault(endpoint.column_name, endpoint)
        if not unique:
            return {}, False
        select_columns: list[str] = []
        predicates: list[str] = []
        table = ""
        for column_name, endpoint in unique.items():
            column = _quote(column_name, access.policy.engine)
            table = _table_reference(endpoint, access)
            select_columns.append(column)
            predicates.append(
                f"({column} IS NOT NULL AND "
                f"{_keyword_predicate(column, keyword, access.policy.engine)})"
            )
        result = self._execute(
            access,
            (
                f"SELECT {', '.join(select_columns)} FROM {table} "
                f"WHERE {' OR '.join(predicates)} LIMIT {_MAX_MATCHED_KEYS + 1}"
            ),
        )
        rows = list(result.rows)
        truncated = len(rows) > _MAX_MATCHED_KEYS
        grouped: dict[str, list[Any]] = {}
        needle = keyword.casefold()
        column_names = list(unique)
        for row in rows[:_MAX_MATCHED_KEYS]:
            for index, key in enumerate(row):
                if key is None or needle not in str(key).casefold():
                    continue
                bucket = grouped.setdefault(column_names[index], [])
                if key not in bucket:
                    bucket.append(key)
        return grouped, truncated

    def _columns(
        self,
        access: ResolvedDatabaseAccess,
        endpoint: TableRelationEndpoint,
    ) -> list[RelationRecordColumn]:
        try:
            with self._connector_manager.lease(access.spec) as connector:
                result = connector.search_objects(
                    SearchObjectsRequest(
                        object_type=DatabaseObjectType.TABLE,
                        schema=endpoint.schema_name,
                        glob=endpoint.table_name,
                        detail=SearchDetail.FULL,
                        limit=1,
                    ),
                    access.policy,
                )
            objects = list(result.objects)
            if not objects:
                return []
            raw_columns = list(getattr(objects[0], "details", {}).get("columns", []))
            return [
                RelationRecordColumn(
                    name=str(item.get("name", "")),
                    type=str(item.get("type", "")),
                    comment=str(item.get("comment", "") or ""),
                    relation_key=str(item.get("name", "")) == endpoint.column_name,
                )
                for item in raw_columns
                if item.get("name")
            ]
        except Exception:
            # Comments enrich the view but never make otherwise valid data unreadable.
            return []

    def _resolve(
        self,
        workspace_id: str,
        environment: str,
        database_key: str,
        *,
        require_query: bool,
    ) -> ResolvedDatabaseAccess:
        try:
            return self._database_access.resolve_workspace_database(
                workspace_id=workspace_id,
                environment=environment,
                mcp_alias=database_key,
                require_query=require_query,
            )
        except DatabaseAccessError as exc:
            raise RelationRecordExplorerError(str(exc), code=exc.code) from exc

    def _execute(self, access: ResolvedDatabaseAccess, statement: str):
        try:
            validated = self._sql_policy.validate(
                statement,
                policy_as_safety_context(access.policy),
            )
            with self._connector_manager.lease(access.spec) as connector:
                return connector.execute_query(validated.sql, access.policy)
        except (
            QueryPolicyError,
            ConnectorManagerError,
            DatabaseConnectorError,
            ResultFormattingError,
        ) as exc:
            raise RelationRecordExplorerError(
                "关联数据查询失败",
                code=getattr(exc, "code", "relation_record_query_failed"),
            ) from exc


def _endpoints_for_table(
    relation: TableRelationView,
    table: RelationRecordTable,
) -> tuple[TableRelationEndpoint, TableRelationEndpoint]:
    identity = (table.database_key, table.schema_name, table.table_name)
    child = (relation.child.database_key, relation.child.schema_name, relation.child.table_name)
    if child == identity:
        return relation.child, relation.parent
    return relation.parent, relation.child


def _empty_card(
    relation: TableRelationView,
    source: TableRelationEndpoint,
    target: TableRelationEndpoint,
    columns: list[RelationRecordColumn],
) -> RelationRecordCard:
    return RelationRecordCard(
        edge_id=relation.edge_id,
        relation_id=relation.relation_id,
        cardinality=relation.db_cardinality,
        source_column=source.column_name or "",
        target=RelationRecordTable(
            database_key=target.database_key,
            schema_name=target.schema_name,
            table_name=target.table_name,
        ),
        target_column=target.column_name or "",
        columns=columns,
        page=RelationRecordPage(),
    )


def _table_reference(endpoint: TableRelationEndpoint, access: ResolvedDatabaseAccess) -> str:
    engine = access.policy.engine
    table = _quote(endpoint.table_name, engine)
    if engine == "postgresql":
        return f"{_quote(endpoint.schema_name, engine)}.{table}"
    return table


def _quote(value: str, engine: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise RelationRecordExplorerError("表关联包含不能安全查询的标识符")
    marker = '"' if engine == "postgresql" else "`"
    return f"{marker}{value}{marker}"


def _literal(value: Any, engine: str) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def _keyword_predicate(column: str, keyword: str, engine: str) -> str:
    literal = _literal(keyword, engine)
    if engine == "clickhouse":
        return f"positionCaseInsensitive(toString({column}), {literal}) > 0"
    if engine == "postgresql":
        return f"CAST({column} AS TEXT) ILIKE '%' || {literal} || '%'"
    return f"CAST({column} AS CHAR) LIKE CONCAT('%', {literal}, '%')"
