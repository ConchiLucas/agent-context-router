from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from itertools import islice
from time import perf_counter
from typing import Any
from uuid import uuid4

import clickhouse_connect
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from context_router.database.errors import DatabaseConnectorError
from context_router.database.models import (
    Column,
    ConnectorCapabilities,
    ConnectorSpec,
    DatabaseObject,
    DatabaseObjectType,
    DiscoveredDatabase,
    EffectiveQueryPolicy,
    QueryResult,
    SearchDetail,
    SearchObjectsRequest,
    SearchObjectsResult,
    TruncationReason,
)

_CLICKHOUSE_SYSTEM_DATABASES = {"information_schema", "system"}
_VIEW_ENGINES = {"view", "materializedview", "liveview", "windowview"}
_TIMEOUT_ERROR_CODES = {159}
_TIMEOUT_ERROR_NAMES = {"TIMEOUT_EXCEEDED"}
_CANCELLED_ERROR_CODES = {394}
_CANCELLED_ERROR_NAMES = {"QUERY_WAS_CANCELLED"}


class ClickHouseConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str = Field(default="default", min_length=1, max_length=255)
    password: str = Field(default="", repr=False)
    secure: bool = False
    verify: bool = True
    bootstrap_database: str = Field(default="default", min_length=1, max_length=255)
    connect_timeout_seconds: float = Field(default=8, gt=0, le=60)
    send_receive_timeout_seconds: float = Field(default=15, gt=0, le=300)

    @property
    def resolved_port(self) -> int:
        return self.port or (8443 if self.secure else 8123)


class ClickHouseConnector:
    capabilities = ConnectorCapabilities(
        discover_databases=True,
        search_schemas=True,
        search_tables=True,
        search_views=True,
        search_columns=True,
        search_indexes=True,
        execute_readonly_query=True,
    )

    def __init__(self, spec: ConnectorSpec) -> None:
        if spec.engine != "clickhouse":
            raise DatabaseConnectorError(
                "invalid_connection_config",
                "ClickHouse Connector 收到了不匹配的数据库类型",
            )
        try:
            self._config = ClickHouseConnectionConfig.model_validate(dict(spec.connection_config))
        except ValidationError as exc:
            raise DatabaseConnectorError(
                "invalid_connection_config",
                "ClickHouse 连接配置无效",
            ) from exc
        self._spec = spec
        self._closed = False
        try:
            self._client = clickhouse_connect.get_client(
                host=self._config.host.strip(),
                port=self._config.resolved_port,
                username=self._config.username.strip(),
                password=self._config.password,
                database=spec.remote_name,
                secure=self._config.secure,
                verify=self._config.verify,
                connect_timeout=self._config.connect_timeout_seconds,
                send_receive_timeout=self._config.send_receive_timeout_seconds,
            )
        except Exception as exc:
            raise DatabaseConnectorError(
                "connection_failed",
                "无法连接 ClickHouse",
            ) from exc

    @property
    def engine(self) -> str:
        return "clickhouse"

    def ping(self) -> None:
        self._ensure_open()
        try:
            self._client.command("SELECT 1")
        except Exception as exc:
            raise DatabaseConnectorError("connection_failed", "ClickHouse 连接测试失败") from exc

    def discover_databases(self) -> list[DiscoveredDatabase]:
        self._ensure_open()
        result = self._catalog_query("SELECT name FROM system.databases ORDER BY name")
        return [
            DiscoveredDatabase(
                name=str(row[0]),
                system_database=str(row[0]).casefold() in _CLICKHOUSE_SYSTEM_DATABASES,
                metadata={"discovery": "system.databases"},
            )
            for row in result.result_rows
        ]

    def search_objects(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
    ) -> SearchObjectsResult:
        self._ensure_open()
        self._validate_policy(policy)
        if request.schema and request.schema.casefold() != policy.current_database.casefold():
            raise DatabaseConnectorError(
                "query_rejected",
                "请求的数据库不在当前项目授权范围内",
            )
        started = perf_counter()
        limit = self._detail_limit(request)
        if request.object_type is DatabaseObjectType.SCHEMA:
            objects = self._search_schemas(request, policy, limit)
        elif request.object_type in {DatabaseObjectType.TABLE, DatabaseObjectType.VIEW}:
            objects = self._search_tables(request, policy, limit)
        elif request.object_type is DatabaseObjectType.COLUMN:
            objects = self._search_columns(request, policy, limit)
        elif request.object_type is DatabaseObjectType.INDEX:
            objects = self._search_indexes(request, policy, limit)
        else:  # pragma: no cover - enum protects this path
            raise DatabaseConnectorError("object_type_not_supported", "不支持的数据库对象类型")

        truncated = len(objects) > limit
        if truncated:
            objects = objects[:limit]
        return SearchObjectsResult(
            objects=objects,
            elapsed_ms=_elapsed_ms(started),
            truncated=truncated,
            truncation_reason=TruncationReason.OBJECTS if truncated else None,
        )

    def execute_query(self, sql: str, policy: EffectiveQueryPolicy) -> QueryResult:
        self._ensure_open()
        self._validate_policy(policy)
        settings = {
            "readonly": 1,
            "query_id": uuid4().hex,
            "max_execution_time": max(policy.query_timeout_ms / 1000, 0.1),
            "max_result_rows": policy.max_rows + 1,
            "result_overflow_mode": "break",
            "max_result_bytes": policy.max_result_bytes,
            "max_threads": 4,
            "max_rows_to_read": 10_000_000,
            "max_bytes_to_read": 1_000_000_000,
            "max_memory_usage": 1_000_000_000,
        }
        started = perf_counter()
        try:
            stream = self._client.query_rows_stream(
                sql,
                settings=settings,
                use_none=True,
            )
            source = stream.source
            columns = tuple(
                Column(name=str(name), type=_clickhouse_type_name(type_value))
                for name, type_value in zip(source.column_names, source.column_types, strict=True)
            )
            with stream as rows_stream:
                rows = list(islice(rows_stream, policy.max_rows + 1))
        except Exception as exc:
            interruption_code = _query_interruption_code(exc)
            if interruption_code is not None:
                raise DatabaseConnectorError(
                    interruption_code,
                    (
                        "ClickHouse 查询超时"
                        if interruption_code == "query_timeout"
                        else "ClickHouse 查询已取消"
                    ),
                ) from exc
            raise DatabaseConnectorError("query_failed", "ClickHouse 查询执行失败") from exc

        truncated = len(rows) > policy.max_rows
        return QueryResult(
            columns=columns,
            rows=rows,
            elapsed_ms=_elapsed_ms(started),
            truncated=truncated,
            truncation_reason=TruncationReason.ROWS if truncated else None,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._client.close()

    def _search_schemas(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
        limit: int,
    ) -> list[DatabaseObject]:
        result = self._catalog_query(
            """SELECT name FROM system.databases
            WHERE name = {database:String} AND match(name, {pattern:String})
            ORDER BY name LIMIT {limit:UInt32}""",
            {
                "database": policy.current_database,
                "pattern": _glob_regex(request.glob),
                "limit": limit + 1,
            },
        )
        return [
            DatabaseObject(name=str(row[0]), schema=None, kind="schema")
            for row in result.result_rows
        ]

    def _search_tables(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
        limit: int,
    ) -> list[DatabaseObject]:
        view_filter = (
            "lower(engine) IN ('view','materializedview','liveview','windowview')"
            if request.object_type is DatabaseObjectType.VIEW
            else "lower(engine) NOT IN ('view','materializedview','liveview','windowview')"
        )
        result = self._catalog_query(
            f"""SELECT name, database, engine, total_rows, total_bytes, comment,
                       sorting_key, primary_key, partition_key
                FROM system.tables
                WHERE database = {{database:String}}
                  AND match(name, {{pattern:String}})
                  AND {view_filter}
                ORDER BY name LIMIT {{limit:UInt32}}""",
            {
                "database": policy.current_database,
                "pattern": _glob_regex(request.glob),
                "limit": limit + 1,
            },
        )
        full_columns: Mapping[str, list[dict[str, Any]]] = {}
        if request.detail is SearchDetail.FULL and result.result_rows:
            full_columns = self._columns_for_tables(
                policy.current_database,
                [str(row[0]) for row in result.result_rows[:limit]],
            )

        objects: list[DatabaseObject] = []
        for row in result.result_rows:
            details: dict[str, Any] = {}
            if request.detail in {SearchDetail.SUMMARY, SearchDetail.FULL}:
                details.update(
                    engine=str(row[2]),
                    estimated_rows=_optional_int(row[3]),
                    estimated_bytes=_optional_int(row[4]),
                    comment=str(row[5]) if row[5] else None,
                )
            if request.detail is SearchDetail.FULL:
                details.update(
                    sorting_key=str(row[6]) if row[6] else None,
                    primary_key=str(row[7]) if row[7] else None,
                    partition_key=str(row[8]) if row[8] else None,
                    columns=full_columns.get(str(row[0]), []),
                )
            objects.append(
                DatabaseObject(
                    name=str(row[0]),
                    schema=str(row[1]),
                    kind="view" if str(row[2]).casefold() in _VIEW_ENGINES else "table",
                    details=details,
                )
            )
        return objects

    def _search_columns(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
        limit: int,
    ) -> list[DatabaseObject]:
        result = self._catalog_query(
            """SELECT name, database, table, type, default_kind, default_expression,
                      comment, is_in_partition_key, is_in_sorting_key, is_in_primary_key
               FROM system.columns
               WHERE database = {database:String}
                 AND ({table:String} = '' OR table = {table:String})
                 AND match(name, {pattern:String})
               ORDER BY table, position LIMIT {limit:UInt32}""",
            {
                "database": policy.current_database,
                "table": request.table or "",
                "pattern": _glob_regex(request.glob),
                "limit": limit + 1,
            },
        )
        objects: list[DatabaseObject] = []
        for row in result.result_rows:
            details: dict[str, Any] = {"table": str(row[2]), "type": str(row[3])}
            if request.detail in {SearchDetail.SUMMARY, SearchDetail.FULL}:
                details["comment"] = str(row[6]) if row[6] else None
            if request.detail is SearchDetail.FULL:
                details.update(
                    default_kind=str(row[4]) if row[4] else None,
                    default_expression=str(row[5]) if row[5] else None,
                    in_partition_key=bool(row[7]),
                    in_sorting_key=bool(row[8]),
                    in_primary_key=bool(row[9]),
                )
            objects.append(
                DatabaseObject(
                    name=str(row[0]),
                    schema=str(row[1]),
                    kind="column",
                    details=details,
                )
            )
        return objects

    def _search_indexes(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
        limit: int,
    ) -> list[DatabaseObject]:
        result = self._catalog_query(
            """SELECT name, database, table, type, type_full, expr, granularity
               FROM system.data_skipping_indices
               WHERE database = {database:String}
                 AND ({table:String} = '' OR table = {table:String})
                 AND match(name, {pattern:String})
               ORDER BY table, name LIMIT {limit:UInt32}""",
            {
                "database": policy.current_database,
                "table": request.table or "",
                "pattern": _glob_regex(request.glob),
                "limit": limit + 1,
            },
        )
        objects: list[DatabaseObject] = []
        for row in result.result_rows:
            details: dict[str, Any] = {"table": str(row[2]), "type": str(row[3])}
            if request.detail is SearchDetail.FULL:
                details.update(
                    type_full=str(row[4]),
                    expression=str(row[5]),
                    granularity=int(row[6]),
                )
            objects.append(
                DatabaseObject(
                    name=str(row[0]),
                    schema=str(row[1]),
                    kind="index",
                    details=details,
                )
            )
        return objects

    def _columns_for_tables(
        self,
        database: str,
        tables: Sequence[str],
    ) -> Mapping[str, list[dict[str, Any]]]:
        result = self._catalog_query(
            """SELECT table, name, type, default_kind, default_expression, comment,
                      is_in_partition_key, is_in_sorting_key, is_in_primary_key
               FROM system.columns
               WHERE database = {database:String}
                 AND has({tables:Array(String)}, table)
               ORDER BY table, position""",
            {"database": database, "tables": list(tables)},
        )
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in result.result_rows:
            grouped[str(row[0])].append(
                {
                    "name": str(row[1]),
                    "type": str(row[2]),
                    "default_kind": str(row[3]) if row[3] else None,
                    "default_expression": str(row[4]) if row[4] else None,
                    "comment": str(row[5]) if row[5] else None,
                    "in_partition_key": bool(row[6]),
                    "in_sorting_key": bool(row[7]),
                    "in_primary_key": bool(row[8]),
                }
            )
        return grouped

    def _catalog_query(
        self,
        statement: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> Any:
        try:
            return self._client.query(
                statement,
                parameters=dict(parameters) if parameters is not None else None,
                settings={"readonly": 1, "max_execution_time": 10, "max_threads": 2},
                use_none=True,
            )
        except Exception as exc:
            raise DatabaseConnectorError(
                "catalog_query_failed",
                "ClickHouse 元数据读取失败",
            ) from exc

    def _validate_policy(self, policy: EffectiveQueryPolicy) -> None:
        if policy.engine != self.engine:
            raise DatabaseConnectorError("query_rejected", "查询策略与数据库类型不匹配")
        if policy.current_database.casefold() != self._spec.remote_name.casefold():
            raise DatabaseConnectorError("query_rejected", "查询策略与目标数据库不匹配")
        allowed = {schema.casefold() for schema in policy.allowed_schemas}
        if allowed and policy.current_database.casefold() not in allowed:
            raise DatabaseConnectorError("query_rejected", "目标数据库不在允许范围内")

    @staticmethod
    def _detail_limit(request: SearchObjectsRequest) -> int:
        hard_limit = {
            SearchDetail.NAMES: 500,
            SearchDetail.SUMMARY: 100,
            SearchDetail.FULL: 20,
        }[request.detail]
        return min(request.limit, hard_limit)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DatabaseConnectorError("connection_failed", "ClickHouse 连接已经关闭")


def _glob_regex(pattern: str) -> str:
    pieces: list[str] = ["^"]
    for character in pattern:
        if character == "*":
            pieces.append(".*")
        elif character == "?":
            pieces.append(".")
        else:
            pieces.append(re.escape(character))
    pieces.append("$")
    return "".join(pieces)


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _clickhouse_type_name(value: Any) -> str:
    return str(getattr(value, "name", value))


def _query_interruption_code(error: Exception) -> str | None:
    code = getattr(error, "code", None)
    name = str(getattr(error, "name", "")).upper()
    if (
        code in _TIMEOUT_ERROR_CODES
        or name in _TIMEOUT_ERROR_NAMES
        or error.__class__.__name__ in {"ConnectTimeoutError", "ReadTimeoutError", "TimeoutError"}
    ):
        return "query_timeout"
    if code in _CANCELLED_ERROR_CODES or name in _CANCELLED_ERROR_NAMES:
        return "query_cancelled"
    return None
