from __future__ import annotations

import re
from time import perf_counter
from typing import Any

import pymysql
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

_MYSQL_SYSTEM_DATABASES = {"information_schema", "mysql", "performance_schema", "sys"}
_MYSQL_TIMEOUT_ERROR_CODES = {1969, 3024}
_MYSQL_CANCELLED_ERROR_CODES = {1317}


class MySQLConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=3306, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(default="", repr=False)
    connect_timeout_seconds: int = Field(default=8, ge=1, le=60)
    read_timeout_seconds: int = Field(default=30, ge=1, le=300)
    write_timeout_seconds: int = Field(default=30, ge=1, le=300)


class MySQLConnector:
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
        if spec.engine not in {"mysql", "mariadb"}:
            raise DatabaseConnectorError("invalid_connection_config", "MySQL 类型不匹配")
        values = dict(spec.connection_config)
        values.setdefault("username", values.get("user"))
        values.setdefault("password", values.get("passwd", ""))
        try:
            self._config = MySQLConnectionConfig.model_validate(values)
        except ValidationError as exc:
            raise DatabaseConnectorError("invalid_connection_config", "MySQL 连接配置无效") from exc
        self._spec = spec
        self._engine = spec.engine
        self._closed = False

    @property
    def engine(self) -> str:
        return self._engine

    def ping(self) -> None:
        try:
            connection = self._connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            finally:
                connection.close()
        except pymysql.MySQLError as exc:
            raise DatabaseConnectorError("connection_failed", "MySQL 连接测试失败") from exc

    def discover_databases(self) -> list[DiscoveredDatabase]:
        try:
            connection = self._connect(database=None)
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW DATABASES")
                    rows = cursor.fetchall()
            finally:
                connection.close()
        except pymysql.MySQLError as exc:
            raise DatabaseConnectorError(
                "catalog_query_failed",
                "MySQL 数据库清单读取失败",
            ) from exc
        return [
            DiscoveredDatabase(
                name=str(row[0]),
                system_database=str(row[0]).casefold() in _MYSQL_SYSTEM_DATABASES,
                metadata={"discovery": "SHOW DATABASES"},
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
        connection = None
        try:
            connection = self._connect()
            with connection.cursor() as cursor:
                self._configure_catalog_transaction(cursor, policy)
                rows = self._search_rows(cursor, request, policy, limit + 1)
                objects = [self._row_to_object(request, row) for row in rows[:limit]]
                if request.detail is SearchDetail.FULL and request.object_type in {
                    DatabaseObjectType.TABLE,
                    DatabaseObjectType.VIEW,
                }:
                    objects = self._enrich_relations(cursor, objects, policy.current_database)
                elif (
                    request.detail is SearchDetail.FULL
                    and request.object_type is DatabaseObjectType.INDEX
                ):
                    objects = self._enrich_indexes(cursor, objects, policy.current_database)
        except pymysql.MySQLError as exc:
            interruption_code = _query_interruption_code(exc)
            if interruption_code is not None:
                raise DatabaseConnectorError(
                    interruption_code,
                    (
                        "MySQL 元数据读取超时"
                        if interruption_code == "query_timeout"
                        else "MySQL 元数据读取已取消"
                    ),
                ) from exc
            raise DatabaseConnectorError("catalog_query_failed", "MySQL 元数据读取失败") from exc
        finally:
            if connection is not None:
                try:
                    connection.rollback()
                finally:
                    connection.close()
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
        connection = None
        try:
            connection = self._connect(cursorclass=pymysql.cursors.SSCursor)
            with connection.cursor() as cursor:
                if self._engine == "mysql":
                    cursor.execute(
                        "SET SESSION MAX_EXECUTION_TIME = %s",
                        (policy.query_timeout_ms,),
                    )
                else:
                    cursor.execute(
                        "SET SESSION max_statement_time = %s",
                        (policy.query_timeout_ms / 1000,),
                    )
                cursor.execute("START TRANSACTION READ ONLY")
                cursor.execute(sql_text)
                rows = cursor.fetchmany(policy.max_rows + 1)
                description = cursor.description or ()
            connection.rollback()
        except pymysql.MySQLError as exc:
            interruption_code = _query_interruption_code(exc)
            if interruption_code is not None:
                raise DatabaseConnectorError(
                    interruption_code,
                    (
                        "MySQL 查询超时"
                        if interruption_code == "query_timeout"
                        else "MySQL 查询已取消"
                    ),
                ) from exc
            raise DatabaseConnectorError("query_failed", "MySQL 查询执行失败") from exc
        finally:
            if connection is not None:
                connection.close()
        columns = tuple(Column(name=str(item[0]), type=str(item[1])) for item in description)
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
        cursor: Any,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
        limit: int,
    ) -> list[tuple[Any, ...]]:
        pattern = _glob_regex(request.glob)
        database = policy.current_database
        if request.schema and request.schema.casefold() != database.casefold():
            raise DatabaseConnectorError("query_rejected", "不允许跨数据库搜索")
        if request.object_type is DatabaseObjectType.SCHEMA:
            statement = """SELECT schema_info.SCHEMA_NAME, NULL, 'schema'
                FROM information_schema.SCHEMATA AS schema_info
                WHERE schema_info.SCHEMA_NAME = %s
                  AND schema_info.SCHEMA_NAME REGEXP %s
                ORDER BY schema_info.SCHEMA_NAME LIMIT %s"""
            params = (database, pattern, limit)
        elif request.object_type in {DatabaseObjectType.TABLE, DatabaseObjectType.VIEW}:
            expected = "VIEW" if request.object_type is DatabaseObjectType.VIEW else "BASE TABLE"
            fields = """relation.TABLE_NAME, relation.TABLE_SCHEMA,
                CASE WHEN relation.TABLE_TYPE = 'VIEW' THEN 'view' ELSE 'table' END"""
            if request.detail is not SearchDetail.NAMES:
                fields += """, relation.ENGINE, relation.TABLE_ROWS,
                    COALESCE(relation.DATA_LENGTH, 0) + COALESCE(relation.INDEX_LENGTH, 0),
                    relation.TABLE_COMMENT"""
            statement = f"""SELECT {fields}
                FROM information_schema.TABLES AS relation
                WHERE relation.TABLE_SCHEMA = %s
                  AND relation.TABLE_NAME REGEXP %s
                  AND relation.TABLE_TYPE = %s
                ORDER BY relation.TABLE_NAME LIMIT %s"""
            params = (database, pattern, expected, limit)
        elif request.object_type is DatabaseObjectType.COLUMN:
            fields = "column_info.COLUMN_NAME, column_info.TABLE_SCHEMA, 'column'"
            if request.detail is not SearchDetail.NAMES:
                fields += """, column_info.TABLE_NAME, column_info.COLUMN_TYPE,
                    column_info.IS_NULLABLE"""
            if request.detail is SearchDetail.FULL:
                fields += """, column_info.COLUMN_DEFAULT, column_info.ORDINAL_POSITION,
                    column_info.EXTRA, column_info.COLUMN_COMMENT,
                    column_info.COLLATION_NAME"""
            statement = f"""SELECT {fields}
                FROM information_schema.COLUMNS AS column_info
                WHERE column_info.TABLE_SCHEMA = %s
                  AND column_info.COLUMN_NAME REGEXP %s
                  AND (%s = '' OR column_info.TABLE_NAME = %s)
                ORDER BY column_info.TABLE_NAME, column_info.ORDINAL_POSITION LIMIT %s"""
            params = (database, pattern, request.table or "", request.table or "", limit)
        else:
            fields = "index_info.INDEX_NAME, index_info.TABLE_SCHEMA, 'index'"
            if request.detail is not SearchDetail.NAMES:
                fields += """, index_info.TABLE_NAME, index_info.INDEX_TYPE,
                    MIN(index_info.NON_UNIQUE)"""
            statement = f"""SELECT {fields}
                FROM information_schema.STATISTICS AS index_info
                WHERE index_info.TABLE_SCHEMA = %s
                  AND index_info.INDEX_NAME REGEXP %s
                  AND (%s = '' OR index_info.TABLE_NAME = %s)
                GROUP BY index_info.INDEX_NAME, index_info.TABLE_SCHEMA,
                         index_info.TABLE_NAME, index_info.INDEX_TYPE
                ORDER BY index_info.TABLE_NAME, index_info.INDEX_NAME LIMIT %s"""
            params = (database, pattern, request.table or "", request.table or "", limit)
        cursor.execute(statement, params)
        return list(cursor.fetchall())

    @staticmethod
    def _row_to_object(
        request: SearchObjectsRequest,
        row: tuple[Any, ...],
    ) -> DatabaseObject:
        details: dict[str, Any] = {}
        if request.object_type in {DatabaseObjectType.TABLE, DatabaseObjectType.VIEW}:
            if request.detail is not SearchDetail.NAMES:
                details = {
                    "engine": str(row[3]) if row[3] else None,
                    "estimated_rows": _optional_int(row[4]),
                    "estimated_bytes": _optional_int(row[5]),
                    "comment": str(row[6]) if row[6] else None,
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
                    extra=str(row[8]) if row[8] else "",
                    comment=str(row[9]) if row[9] else "",
                    collation=str(row[10]) if row[10] else None,
                )
        elif request.object_type is DatabaseObjectType.INDEX:
            if request.detail is not SearchDetail.NAMES:
                details = {
                    "table": str(row[3]),
                    "type": str(row[4]),
                    "unique": not bool(row[5]),
                    "primary": str(row[0]).casefold() == "primary",
                }
        return DatabaseObject(
            name=str(row[0]),
            schema=str(row[1]) if row[1] is not None else None,
            kind=str(row[2]),
            details=details,
        )

    def _configure_catalog_transaction(
        self,
        cursor: Any,
        policy: EffectiveQueryPolicy,
    ) -> None:
        if self._engine == "mysql":
            cursor.execute(
                "SET SESSION MAX_EXECUTION_TIME = %s",
                (policy.query_timeout_ms,),
            )
        else:
            cursor.execute(
                "SET SESSION max_statement_time = %s",
                (policy.query_timeout_ms / 1000,),
            )
        cursor.execute("START TRANSACTION READ ONLY")

    def _enrich_relations(
        self,
        cursor: Any,
        objects: list[DatabaseObject],
        database: str,
    ) -> list[DatabaseObject]:
        names = [item.name for item in objects]
        if not names:
            return objects
        placeholders = _placeholders(len(names))
        params = (database, *names)
        cursor.execute(
            f"""SELECT column_info.TABLE_NAME, column_info.COLUMN_NAME,
                       column_info.COLUMN_TYPE, column_info.IS_NULLABLE,
                       column_info.COLUMN_DEFAULT, column_info.ORDINAL_POSITION,
                       column_info.EXTRA, column_info.COLUMN_COMMENT,
                       column_info.COLLATION_NAME
                FROM information_schema.COLUMNS AS column_info
                WHERE column_info.TABLE_SCHEMA = %s
                  AND column_info.TABLE_NAME IN ({placeholders})
                ORDER BY column_info.TABLE_NAME, column_info.ORDINAL_POSITION""",
            params,
        )
        columns = cursor.fetchall()
        cursor.execute(
            f"""SELECT constraint_info.TABLE_NAME, constraint_info.CONSTRAINT_NAME,
                       constraint_info.CONSTRAINT_TYPE, key_info.COLUMN_NAME,
                       key_info.ORDINAL_POSITION
                FROM information_schema.TABLE_CONSTRAINTS AS constraint_info
                JOIN information_schema.KEY_COLUMN_USAGE AS key_info
                  ON key_info.CONSTRAINT_SCHEMA = constraint_info.CONSTRAINT_SCHEMA
                 AND key_info.CONSTRAINT_NAME = constraint_info.CONSTRAINT_NAME
                 AND key_info.TABLE_SCHEMA = constraint_info.TABLE_SCHEMA
                 AND key_info.TABLE_NAME = constraint_info.TABLE_NAME
                WHERE constraint_info.TABLE_SCHEMA = %s
                  AND constraint_info.TABLE_NAME IN ({placeholders})
                  AND constraint_info.CONSTRAINT_TYPE IN (
                      'PRIMARY KEY', 'UNIQUE', 'FOREIGN KEY'
                  )
                ORDER BY constraint_info.TABLE_NAME,
                         constraint_info.CONSTRAINT_NAME, key_info.ORDINAL_POSITION""",
            params,
        )
        keys = cursor.fetchall()
        cursor.execute(
            f"""SELECT index_info.TABLE_NAME, index_info.INDEX_NAME,
                       index_info.INDEX_TYPE, index_info.NON_UNIQUE,
                       index_info.COLUMN_NAME, index_info.SEQ_IN_INDEX,
                       index_info.SUB_PART, index_info.COLLATION,
                       index_info.NULLABLE, index_info.INDEX_COMMENT
                FROM information_schema.STATISTICS AS index_info
                WHERE index_info.TABLE_SCHEMA = %s
                  AND index_info.TABLE_NAME IN ({placeholders})
                ORDER BY index_info.TABLE_NAME, index_info.INDEX_NAME,
                         index_info.SEQ_IN_INDEX""",
            params,
        )
        indexes = cursor.fetchall()
        relation_columns: dict[str, list[dict[str, Any]]] = {}
        for row in columns:
            relation_columns.setdefault(str(row[0]), []).append(
                {
                    "name": str(row[1]),
                    "type": str(row[2]),
                    "nullable": str(row[3]).casefold() == "yes",
                    "default": str(row[4]) if row[4] is not None else None,
                    "ordinal_position": int(row[5]),
                    "extra": str(row[6]) if row[6] else "",
                    "comment": str(row[7]) if row[7] else "",
                    "collation": str(row[8]) if row[8] else None,
                }
            )
        relation_keys = _group_key_rows(keys)
        relation_indexes = _group_index_rows(indexes)
        enriched: list[DatabaseObject] = []
        for item in objects:
            details = dict(item.details)
            details.update(
                columns=relation_columns.get(item.name, []),
                keys=relation_keys.get(item.name, []),
                indexes=relation_indexes.get(item.name, []),
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
        cursor: Any,
        objects: list[DatabaseObject],
        database: str,
    ) -> list[DatabaseObject]:
        pairs = [(str(item.details["table"]), item.name) for item in objects]
        if not pairs:
            return objects
        values = _values_placeholders(len(pairs), width=2)
        cursor.execute(
            f"""SELECT index_detail.TABLE_NAME, index_detail.INDEX_NAME,
                       index_detail.COLUMN_NAME, index_detail.SEQ_IN_INDEX,
                       index_detail.SUB_PART, index_detail.COLLATION,
                       index_detail.NULLABLE, index_detail.INDEX_COMMENT
                FROM information_schema.STATISTICS AS index_detail
                WHERE index_detail.TABLE_SCHEMA = %s
                  AND (index_detail.TABLE_NAME, index_detail.INDEX_NAME) IN ({values})
                ORDER BY index_detail.TABLE_NAME, index_detail.INDEX_NAME,
                         index_detail.SEQ_IN_INDEX""",
            (database, *_flatten(pairs)),
        )
        rows = cursor.fetchall()
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        comments: dict[tuple[str, str], str | None] = {}
        for row in rows:
            key = (str(row[0]), str(row[1]))
            grouped.setdefault(key, []).append(
                {
                    "name": str(row[2]) if row[2] is not None else None,
                    "position": int(row[3]),
                    "prefix_length": _optional_int(row[4]),
                    "order": str(row[5]) if row[5] else None,
                    "nullable": str(row[6]).casefold() == "yes",
                }
            )
            comments[key] = str(row[7]) if row[7] else None
        enriched: list[DatabaseObject] = []
        for item in objects:
            key = (str(item.details["table"]), item.name)
            details = dict(item.details)
            details["columns"] = grouped.get(key, [])
            details["comment"] = comments.get(key)
            enriched.append(
                DatabaseObject(
                    name=item.name,
                    schema=item.schema,
                    kind=item.kind,
                    details=details,
                )
            )
        return enriched

    def _connect(self, *, database: str | None = "target", cursorclass=None):
        self._ensure_open()
        kwargs: dict[str, Any] = {
            "host": self._config.host.strip(),
            "port": self._config.port,
            "user": self._config.username.strip(),
            "password": self._config.password,
            "connect_timeout": self._config.connect_timeout_seconds,
            "read_timeout": self._config.read_timeout_seconds,
            "write_timeout": self._config.write_timeout_seconds,
            "charset": "utf8mb4",
            "autocommit": False,
        }
        if database == "target":
            kwargs["database"] = self._spec.remote_name
        elif database is not None:
            kwargs["database"] = database
        if cursorclass is not None:
            kwargs["cursorclass"] = cursorclass
        return pymysql.connect(**kwargs)

    def _ensure_open(self) -> None:
        if self._closed:
            raise DatabaseConnectorError("connection_failed", "MySQL Connector 已关闭")

    def _ensure_policy(self, policy: EffectiveQueryPolicy) -> None:
        self._ensure_open()
        if policy.engine != self.engine or policy.current_database != self._spec.remote_name:
            raise DatabaseConnectorError("query_rejected", "查询策略与 MySQL 目标不匹配")
        if policy.allowed_schemas and any(
            schema.casefold() != self._spec.remote_name.casefold()
            for schema in policy.allowed_schemas
        ):
            raise DatabaseConnectorError("query_rejected", "不允许跨数据库查询")


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


def _query_interruption_code(error: pymysql.MySQLError) -> str | None:
    error_code = error.args[0] if error.args and isinstance(error.args[0], int) else None
    if error_code in _MYSQL_TIMEOUT_ERROR_CODES:
        return "query_timeout"
    if error_code in _MYSQL_CANCELLED_ERROR_CODES:
        return "query_cancelled"
    return None


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _placeholders(count: int) -> str:
    return ", ".join(["%s"] * count)


def _values_placeholders(count: int, *, width: int) -> str:
    return ", ".join(f"({', '.join(['%s'] * width)})" for _ in range(count))


def _flatten(rows: list[tuple[Any, ...]]) -> list[Any]:
    return [value for row in rows for value in row]


def _group_key_rows(rows: list[tuple[Any, ...]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[tuple[str, str], list[str]]] = {}
    for row in rows:
        table = str(row[0])
        key = (str(row[1]), str(row[2]))
        grouped.setdefault(table, {}).setdefault(key, []).append(str(row[3]))
    return {
        table: [
            {"name": name, "type": key_type, "columns": columns}
            for (name, key_type), columns in keys.items()
        ]
        for table, keys in grouped.items()
    }


def _group_index_rows(rows: list[tuple[Any, ...]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        table = str(row[0])
        name = str(row[1])
        index = grouped.setdefault(table, {}).setdefault(
            name,
            {
                "name": name,
                "type": str(row[2]),
                "unique": not bool(row[3]),
                "primary": name.casefold() == "primary",
                "columns": [],
                "comment": str(row[9]) if row[9] else None,
            },
        )
        index["columns"].append(
            {
                "name": str(row[4]) if row[4] is not None else None,
                "position": int(row[5]),
                "prefix_length": _optional_int(row[6]),
                "order": str(row[7]) if row[7] else None,
                "nullable": str(row[8]).casefold() == "yes",
            }
        )
    return {table: list(indexes.values()) for table, indexes in grouped.items()}
