from __future__ import annotations

import re
from time import perf_counter
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
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

_POSTGRES_SYSTEM_DATABASES = {"postgres"}
_POSTGRES_SYSTEM_SCHEMAS = {"information_schema", "pg_catalog"}


class PostgreSQLConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(default="", repr=False)
    database: str = Field(default="postgres", min_length=1, max_length=255)
    connect_timeout_seconds: int = Field(default=8, ge=1, le=60)
    sslmode: str | None = None


class PostgreSQLConnector:
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
        if spec.engine != "postgresql":
            raise DatabaseConnectorError("invalid_connection_config", "PostgreSQL 类型不匹配")
        values = dict(spec.connection_config)
        values.setdefault("username", values.get("user"))
        values.setdefault("password", values.get("passwd", ""))
        try:
            self._config = PostgreSQLConnectionConfig.model_validate(values)
        except ValidationError as exc:
            raise DatabaseConnectorError(
                "invalid_connection_config", "PostgreSQL 连接配置无效"
            ) from exc
        self._spec = spec
        self._closed = False

    @property
    def engine(self) -> str:
        return "postgresql"

    def ping(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1")
        except psycopg.Error as exc:
            raise DatabaseConnectorError("connection_failed", "PostgreSQL 连接测试失败") from exc

    def discover_databases(self) -> list[DiscoveredDatabase]:
        statement = """SELECT datname FROM pg_database
            WHERE datallowconn AND NOT datistemplate ORDER BY datname"""
        try:
            with self._connect(database=self._config.database) as connection:
                rows = connection.execute(statement).fetchall()
        except psycopg.Error as exc:
            raise DatabaseConnectorError(
                "catalog_query_failed", "PostgreSQL 数据库清单读取失败"
            ) from exc
        return [
            DiscoveredDatabase(
                name=str(row[0]),
                system_database=str(row[0]).casefold() in _POSTGRES_SYSTEM_DATABASES,
                metadata={"discovery": "pg_database"},
            )
            for row in rows
        ]

    def search_objects(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
    ) -> SearchObjectsResult:
        self._ensure_policy(policy)
        started = perf_counter()
        limit = min(
            request.limit,
            {SearchDetail.NAMES: 500, SearchDetail.SUMMARY: 100, SearchDetail.FULL: 20}[
                request.detail
            ],
        )
        try:
            with self._connect() as connection:
                with connection.transaction():
                    self._configure_catalog_transaction(connection, policy)
                    rows = self._search_rows(connection, request, policy, limit + 1)
                    objects = [self._row_to_object(request, row) for row in rows[:limit]]
                    if request.detail is SearchDetail.FULL and request.object_type in {
                        DatabaseObjectType.TABLE,
                        DatabaseObjectType.VIEW,
                    }:
                        objects = self._enrich_relations(connection, objects)
                    elif (
                        request.detail is SearchDetail.FULL
                        and request.object_type is DatabaseObjectType.INDEX
                    ):
                        objects = self._enrich_indexes(connection, objects)
        except psycopg.errors.QueryCanceled as exc:
            raise DatabaseConnectorError("query_timeout", "PostgreSQL 元数据读取超时") from exc
        except psycopg.Error as exc:
            raise DatabaseConnectorError(
                "catalog_query_failed", "PostgreSQL 元数据读取失败"
            ) from exc
        truncated = len(rows) > limit
        return SearchObjectsResult(
            objects=objects,
            elapsed_ms=_elapsed_ms(started),
            truncated=truncated,
            truncation_reason=TruncationReason.OBJECTS if truncated else None,
        )

    def execute_query(self, sql_text: str, policy: EffectiveQueryPolicy) -> QueryResult:
        self._ensure_policy(policy)
        started = perf_counter()
        try:
            with self._connect() as connection:
                with connection.transaction():
                    connection.execute("SET TRANSACTION READ ONLY")
                    connection.execute(
                        "SELECT set_config('statement_timeout', %s, true)",
                        (str(policy.query_timeout_ms),),
                    )
                    if policy.allowed_schemas:
                        identifiers = [sql.Identifier(name) for name in policy.allowed_schemas]
                        connection.execute(
                            sql.SQL("SET LOCAL search_path TO {}").format(
                                sql.SQL(", ").join(identifiers)
                            )
                        )
                    with connection.cursor(name=f"context_router_{uuid4().hex}") as cursor:
                        cursor.execute(sql_text)
                        rows = cursor.fetchmany(policy.max_rows + 1)
                        description = cursor.description or ()
        except psycopg.errors.QueryCanceled as exc:
            raise DatabaseConnectorError("query_timeout", "PostgreSQL 查询超时") from exc
        except psycopg.Error as exc:
            raise DatabaseConnectorError("query_failed", "PostgreSQL 查询执行失败") from exc

        columns = tuple(
            Column(name=str(item.name), type=str(item.type_code)) for item in description
        )
        truncated = len(rows) > policy.max_rows
        return QueryResult(
            columns=columns,
            rows=rows,
            elapsed_ms=_elapsed_ms(started),
            truncated=truncated,
            truncation_reason=TruncationReason.ROWS if truncated else None,
        )

    def close(self) -> None:
        self._closed = True

    def _search_rows(
        self,
        connection: Any,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
        limit: int,
    ) -> list[tuple[Any, ...]]:
        pattern = _glob_regex(request.glob)
        allowed = tuple(policy.allowed_schemas)
        params: list[Any]
        if request.object_type is DatabaseObjectType.SCHEMA:
            statement = """SELECT schema_info.schema_name, NULL, 'schema'
                FROM information_schema.schemata AS schema_info
                WHERE schema_info.schema_name ~ %s
                  AND schema_info.schema_name <> 'information_schema'
                  AND schema_info.schema_name NOT LIKE 'pg_%%'"""
            params = [pattern]
            if allowed:
                statement += " AND schema_info.schema_name = ANY(%s)"
                params.append(list(allowed))
            statement += " ORDER BY schema_info.schema_name LIMIT %s"
        elif request.object_type in {DatabaseObjectType.TABLE, DatabaseObjectType.VIEW}:
            relation_kinds = (
                ["v", "m"] if request.object_type is DatabaseObjectType.VIEW else ["r", "p", "f"]
            )
            fields = """relation.relname, namespace.nspname,
                CASE WHEN relation.relkind IN ('v', 'm') THEN 'view' ELSE 'table' END"""
            if request.detail is not SearchDetail.NAMES:
                fields += """, relation.reltuples::bigint,
                    CASE
                        WHEN relation.relkind IN ('r', 'p', 'm')
                        THEN pg_catalog.pg_total_relation_size(relation.oid)
                        ELSE 0
                    END,
                    pg_catalog.obj_description(relation.oid, 'pg_class')"""
            statement = f"""SELECT {fields}
                FROM pg_catalog.pg_class AS relation
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE relation.relname ~ %s
                  AND relation.relkind::text = ANY(%s)
                  AND namespace.nspname <> 'information_schema'
                  AND namespace.nspname NOT LIKE 'pg_%%'"""
            params = [pattern, relation_kinds]
            if request.schema:
                statement += " AND namespace.nspname = %s"
                params.append(request.schema)
            if allowed:
                statement += " AND namespace.nspname = ANY(%s)"
                params.append(list(allowed))
            statement += " ORDER BY namespace.nspname, relation.relname LIMIT %s"
        elif request.object_type is DatabaseObjectType.COLUMN:
            fields = "column_info.column_name, column_info.table_schema, 'column'"
            if request.detail is not SearchDetail.NAMES:
                fields += """, column_info.table_name, column_info.data_type,
                    column_info.is_nullable"""
            if request.detail is SearchDetail.FULL:
                fields += """, column_info.column_default, column_info.ordinal_position,
                    column_info.character_maximum_length, column_info.numeric_precision,
                    column_info.is_generated"""
            statement = f"""SELECT {fields}
                FROM information_schema.columns AS column_info
                WHERE column_info.column_name ~ %s
                  AND column_info.table_schema <> 'information_schema'
                  AND column_info.table_schema NOT LIKE 'pg_%%'"""
            params = [pattern]
            if request.schema:
                statement += " AND column_info.table_schema = %s"
                params.append(request.schema)
            if request.table:
                statement += " AND column_info.table_name = %s"
                params.append(request.table)
            if allowed:
                statement += " AND column_info.table_schema = ANY(%s)"
                params.append(list(allowed))
            statement += """ ORDER BY column_info.table_schema, column_info.table_name,
                column_info.ordinal_position LIMIT %s"""
        else:
            fields = "index_relation.relname, namespace.nspname, 'index'"
            if request.detail is not SearchDetail.NAMES:
                fields += """, table_relation.relname, access_method.amname,
                    index_info.indisunique, index_info.indisprimary"""
            if request.detail is SearchDetail.FULL:
                fields += """, pg_catalog.pg_get_indexdef(index_relation.oid),
                    pg_catalog.pg_get_expr(
                        index_info.indpred, index_info.indrelid, true
                    )"""
            statement = f"""SELECT {fields}
                FROM pg_catalog.pg_class AS index_relation
                JOIN pg_catalog.pg_index AS index_info
                  ON index_info.indexrelid = index_relation.oid
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.oid = index_info.indrelid
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.oid = table_relation.relnamespace
                JOIN pg_catalog.pg_am AS access_method
                  ON access_method.oid = index_relation.relam
                WHERE index_relation.relname ~ %s
                  AND namespace.nspname <> 'information_schema'
                  AND namespace.nspname NOT LIKE 'pg_%%'"""
            params = [pattern]
            if request.schema:
                statement += " AND namespace.nspname = %s"
                params.append(request.schema)
            if request.table:
                statement += " AND table_relation.relname = %s"
                params.append(request.table)
            if allowed:
                statement += " AND namespace.nspname = ANY(%s)"
                params.append(list(allowed))
            statement += """ ORDER BY namespace.nspname, table_relation.relname,
                index_relation.relname LIMIT %s"""
        params.append(limit)
        return list(connection.execute(statement, params).fetchall())

    @staticmethod
    def _row_to_object(
        request: SearchObjectsRequest,
        row: tuple[Any, ...],
    ) -> DatabaseObject:
        details: dict[str, Any] = {}
        if request.object_type in {DatabaseObjectType.TABLE, DatabaseObjectType.VIEW}:
            if request.detail is not SearchDetail.NAMES:
                details = {
                    "estimated_rows": _optional_int(row[3]),
                    "estimated_bytes": _optional_int(row[4]),
                    "comment": str(row[5]) if row[5] else None,
                }
        elif request.object_type is DatabaseObjectType.COLUMN:
            if request.detail is not SearchDetail.NAMES:
                details = {
                    "table": str(row[3]),
                    "type": str(row[4]),
                    "nullable": str(row[5]).casefold() == "yes",
                }
            if request.detail is SearchDetail.FULL:
                details.update(
                    default=str(row[6]) if row[6] is not None else None,
                    ordinal_position=int(row[7]),
                    max_length=_optional_int(row[8]),
                    numeric_precision=_optional_int(row[9]),
                    generated=str(row[10]).casefold() != "never",
                )
        elif request.object_type is DatabaseObjectType.INDEX:
            if request.detail is not SearchDetail.NAMES:
                details = {
                    "table": str(row[3]),
                    "type": str(row[4]),
                    "unique": bool(row[5]),
                    "primary": bool(row[6]),
                }
            if request.detail is SearchDetail.FULL:
                details.update(
                    definition=str(row[7]),
                    predicate=str(row[8]) if row[8] else None,
                )
        return DatabaseObject(
            name=str(row[0]),
            schema=str(row[1]) if row[1] is not None else None,
            kind=str(row[2]),
            details=details,
        )

    @staticmethod
    def _configure_catalog_transaction(connection: Any, policy: EffectiveQueryPolicy) -> None:
        connection.execute("SET TRANSACTION READ ONLY")
        connection.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(policy.query_timeout_ms),),
        )

    def _enrich_relations(
        self,
        connection: Any,
        objects: list[DatabaseObject],
    ) -> list[DatabaseObject]:
        pairs = [(item.schema, item.name) for item in objects if item.schema is not None]
        if not pairs:
            return objects
        values = _values_placeholders(len(pairs), width=2)
        params = _flatten(pairs)
        columns = connection.execute(
            f"""WITH selected_relations(schema_name, relation_name) AS (VALUES {values})
                SELECT selected.schema_name, selected.relation_name,
                       column_info.column_name, column_info.data_type,
                       column_info.is_nullable, column_info.column_default,
                       column_info.ordinal_position, column_info.character_maximum_length,
                       column_info.numeric_precision, column_info.is_generated
                FROM selected_relations AS selected
                JOIN information_schema.columns AS column_info
                  ON column_info.table_schema = selected.schema_name
                 AND column_info.table_name = selected.relation_name
                ORDER BY selected.schema_name, selected.relation_name,
                         column_info.ordinal_position""",
            params,
        ).fetchall()
        keys = connection.execute(
            f"""WITH selected_relations(schema_name, relation_name) AS (VALUES {values})
                SELECT selected.schema_name, selected.relation_name,
                       constraint_info.constraint_name, constraint_info.constraint_type,
                       key_info.column_name, key_info.ordinal_position
                FROM selected_relations AS selected
                JOIN information_schema.table_constraints AS constraint_info
                  ON constraint_info.table_schema = selected.schema_name
                 AND constraint_info.table_name = selected.relation_name
                JOIN information_schema.key_column_usage AS key_info
                  ON key_info.constraint_schema = constraint_info.constraint_schema
                 AND key_info.constraint_name = constraint_info.constraint_name
                 AND key_info.table_schema = constraint_info.table_schema
                 AND key_info.table_name = constraint_info.table_name
                WHERE constraint_info.constraint_type IN (
                    'PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY'
                )
                ORDER BY selected.schema_name, selected.relation_name,
                         constraint_info.constraint_name, key_info.ordinal_position""",
            params,
        ).fetchall()
        indexes = connection.execute(
            f"""WITH selected_relations(schema_name, relation_name) AS (VALUES {values})
                SELECT selected.schema_name, selected.relation_name,
                       index_relation.relname, access_method.amname,
                       index_info.indisunique, index_info.indisprimary,
                       pg_catalog.pg_get_indexdef(index_relation.oid),
                       pg_catalog.pg_get_expr(
                           index_info.indpred, index_info.indrelid, true
                       )
                FROM selected_relations AS selected
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.nspname = selected.schema_name
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.relnamespace = namespace.oid
                 AND table_relation.relname = selected.relation_name
                JOIN pg_catalog.pg_index AS index_info
                  ON index_info.indrelid = table_relation.oid
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_info.indexrelid
                JOIN pg_catalog.pg_am AS access_method
                  ON access_method.oid = index_relation.relam
                ORDER BY selected.schema_name, selected.relation_name,
                         index_relation.relname""",
            params,
        ).fetchall()
        relation_columns: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in columns:
            relation_columns.setdefault((str(row[0]), str(row[1])), []).append(
                {
                    "name": str(row[2]),
                    "type": str(row[3]),
                    "nullable": str(row[4]).casefold() == "yes",
                    "default": str(row[5]) if row[5] is not None else None,
                    "ordinal_position": int(row[6]),
                    "max_length": _optional_int(row[7]),
                    "numeric_precision": _optional_int(row[8]),
                    "generated": str(row[9]).casefold() != "never",
                }
            )
        relation_keys = _group_key_rows(keys)
        relation_indexes: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in indexes:
            relation_indexes.setdefault((str(row[0]), str(row[1])), []).append(
                {
                    "name": str(row[2]),
                    "type": str(row[3]),
                    "unique": bool(row[4]),
                    "primary": bool(row[5]),
                    "definition": str(row[6]),
                    "predicate": str(row[7]) if row[7] else None,
                }
            )
        enriched: list[DatabaseObject] = []
        for item in objects:
            key = (item.schema or "", item.name)
            details = dict(item.details)
            details.update(
                columns=relation_columns.get(key, []),
                keys=relation_keys.get(key, []),
                indexes=relation_indexes.get(key, []),
            )
            enriched.append(
                DatabaseObject(
                    name=item.name,
                    schema=item.schema,
                    kind=item.kind,
                    details=details,
                )
            )
        return enriched

    def _enrich_indexes(
        self,
        connection: Any,
        objects: list[DatabaseObject],
    ) -> list[DatabaseObject]:
        triples = [
            (item.schema, str(item.details["table"]), item.name)
            for item in objects
            if item.schema is not None
        ]
        if not triples:
            return objects
        values = _values_placeholders(len(triples), width=3)
        rows = connection.execute(
            f"""WITH selected_indexes(schema_name, relation_name, index_name) AS (
                    VALUES {values}
                )
                SELECT selected.schema_name, selected.relation_name, selected.index_name,
                       index_column.position,
                       pg_catalog.pg_get_indexdef(
                           index_relation.oid, index_column.position, true
                       )
                FROM selected_indexes AS selected
                JOIN pg_catalog.pg_namespace AS namespace
                  ON namespace.nspname = selected.schema_name
                JOIN pg_catalog.pg_class AS table_relation
                  ON table_relation.relnamespace = namespace.oid
                 AND table_relation.relname = selected.relation_name
                JOIN pg_catalog.pg_index AS index_info
                  ON index_info.indrelid = table_relation.oid
                JOIN pg_catalog.pg_class AS index_relation
                  ON index_relation.oid = index_info.indexrelid
                 AND index_relation.relname = selected.index_name
                CROSS JOIN LATERAL generate_series(
                    1, index_info.indnkeyatts
                ) AS index_column(position)
                ORDER BY selected.schema_name, selected.relation_name,
                         selected.index_name, index_column.position""",
            _flatten(triples),
        ).fetchall()
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault((str(row[0]), str(row[1]), str(row[2])), []).append(
                {"position": int(row[3]), "expression": str(row[4])}
            )
        enriched: list[DatabaseObject] = []
        for item in objects:
            key = (item.schema or "", str(item.details["table"]), item.name)
            details = dict(item.details)
            details["columns"] = grouped.get(key, [])
            enriched.append(
                DatabaseObject(
                    name=item.name,
                    schema=item.schema,
                    kind=item.kind,
                    details=details,
                )
            )
        return enriched

    def _connect(self, *, database: str | None = None):
        self._ensure_open()
        kwargs: dict[str, Any] = {
            "host": self._config.host.strip(),
            "port": self._config.port,
            "user": self._config.username.strip(),
            "password": self._config.password,
            "dbname": database or self._spec.remote_name,
            "connect_timeout": self._config.connect_timeout_seconds,
        }
        if self._config.sslmode:
            kwargs["sslmode"] = self._config.sslmode
        return psycopg.connect(**kwargs)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DatabaseConnectorError("connection_failed", "PostgreSQL Connector 已关闭")

    def _ensure_policy(self, policy: EffectiveQueryPolicy) -> None:
        self._ensure_open()
        if policy.engine != self.engine or policy.current_database != self._spec.remote_name:
            raise DatabaseConnectorError("query_rejected", "查询策略与 PostgreSQL 目标不匹配")
        if policy.allowed_schemas:
            requested = {schema.casefold() for schema in policy.allowed_schemas}
            if requested & _POSTGRES_SYSTEM_SCHEMAS:
                raise DatabaseConnectorError("query_rejected", "系统 Schema 不允许查询")


def _glob_regex(pattern: str) -> str:
    pieces = ["^"]
    for character in pattern:
        replacement = (
            ".*" if character == "*" else "." if character == "?" else re.escape(character)
        )
        pieces.append(replacement)
    pieces.append("$")
    return "".join(pieces)


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _values_placeholders(count: int, *, width: int) -> str:
    return ", ".join(f"({', '.join(['%s'] * width)})" for _ in range(count))


def _flatten(rows: list[tuple[Any, ...]]) -> list[Any]:
    return [value for row in rows for value in row]


def _group_key_rows(rows: list[tuple[Any, ...]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], dict[tuple[str, str], list[str]]] = {}
    for row in rows:
        relation = (str(row[0]), str(row[1]))
        key = (str(row[2]), str(row[3]))
        grouped.setdefault(relation, {}).setdefault(key, []).append(str(row[4]))
    return {
        relation: [
            {"name": name, "type": key_type, "columns": columns}
            for (name, key_type), columns in keys.items()
        ]
        for relation, keys in grouped.items()
    }
