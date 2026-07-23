from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class DatabaseObjectType(StrEnum):
    SCHEMA = "schema"
    TABLE = "table"
    VIEW = "view"
    COLUMN = "column"
    INDEX = "index"


class SearchDetail(StrEnum):
    NAMES = "names"
    SUMMARY = "summary"
    FULL = "full"


class TruncationReason(StrEnum):
    ROWS = "rows"
    BYTES = "bytes"
    OBJECTS = "objects"


@dataclass(frozen=True, slots=True)
class ConnectorCapabilities:
    discover_databases: bool = False
    search_schemas: bool = False
    search_tables: bool = False
    search_views: bool = False
    search_columns: bool = False
    search_indexes: bool = False
    execute_readonly_query: bool = False

    def supports_object_type(self, object_type: DatabaseObjectType | str) -> bool:
        value = DatabaseObjectType(object_type)
        return {
            DatabaseObjectType.SCHEMA: self.search_schemas,
            DatabaseObjectType.TABLE: self.search_tables,
            DatabaseObjectType.VIEW: self.search_views,
            DatabaseObjectType.COLUMN: self.search_columns,
            DatabaseObjectType.INDEX: self.search_indexes,
        }[value]


@dataclass(frozen=True, slots=True)
class ConnectorCacheKey:
    data_source_id: str
    config_version: int
    database_id: str
    database_updated_at: datetime


@dataclass(frozen=True, slots=True)
class ConnectorSpec:
    data_source_id: str
    config_version: int
    database_id: str
    database_updated_at: datetime
    engine: str
    remote_name: str
    connection_config: Mapping[str, Any] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        engine = self.engine.strip().lower()
        if not self.data_source_id.strip():
            raise ValueError("data_source_id must not be empty")
        if self.config_version < 1:
            raise ValueError("config_version must be positive")
        if not self.database_id.strip():
            raise ValueError("database_id must not be empty")
        if not engine:
            raise ValueError("engine must not be empty")
        if not self.remote_name.strip():
            raise ValueError("remote_name must not be empty")
        object.__setattr__(self, "engine", engine)
        object.__setattr__(
            self,
            "connection_config",
            MappingProxyType(deepcopy(dict(self.connection_config))),
        )

    @property
    def cache_key(self) -> ConnectorCacheKey:
        return ConnectorCacheKey(
            data_source_id=self.data_source_id,
            config_version=self.config_version,
            database_id=self.database_id,
            database_updated_at=self.database_updated_at,
        )


@dataclass(frozen=True, slots=True)
class DiscoveredDatabase:
    name: str
    system_database: bool = False
    namespace_type: str = "database"
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SearchObjectsRequest:
    object_type: DatabaseObjectType
    schema: str | None = None
    table: str | None = None
    glob: str = "*"
    detail: SearchDetail = SearchDetail.NAMES
    limit: int = 100

    def __post_init__(self) -> None:
        object.__setattr__(self, "object_type", DatabaseObjectType(self.object_type))
        object.__setattr__(self, "detail", SearchDetail(self.detail))
        if not self.glob:
            raise ValueError("glob must not be empty")
        if self.limit < 1:
            raise ValueError("limit must be positive")

    @property
    def pattern(self) -> str:
        """MCP calls this value ``pattern``; connectors consume a normalized glob."""

        return self.glob


@dataclass(frozen=True, slots=True)
class DatabaseObject:
    name: str
    schema: str | None
    kind: str
    details: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "name": self.name,
            "schema": self.schema,
            "kind": self.kind,
        }
        for key, item in self.details.items():
            if key not in value:
                value[str(key)] = item
        return value


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True, slots=True)
class EffectiveQueryPolicy:
    engine: str
    current_database: str
    readonly: bool
    allowed_schemas: tuple[str, ...]
    max_rows: int
    max_result_bytes: int
    query_timeout_ms: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "engine", self.engine.strip().lower())
        object.__setattr__(
            self,
            "allowed_schemas",
            tuple(schema.strip() for schema in self.allowed_schemas if schema.strip()),
        )
        if not self.engine:
            raise ValueError("engine must not be empty")
        if not self.current_database.strip():
            raise ValueError("current_database must not be empty")
        if not self.readonly:
            raise ValueError("database MCP policy must be read-only")
        if min(self.max_rows, self.max_result_bytes, self.query_timeout_ms) < 1:
            raise ValueError("query limits must be positive")


@dataclass(frozen=True, slots=True)
class SearchObjectsResult:
    objects: Iterable[DatabaseObject | Mapping[str, Any]]
    elapsed_ms: int = 0
    truncated: bool = False
    truncation_reason: TruncationReason | None = None


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: Sequence[Column]
    rows: Iterable[Sequence[Any]]
    elapsed_ms: int = 0
    truncated: bool = False
    truncation_reason: TruncationReason | None = None


@dataclass(frozen=True, slots=True)
class FormattedSearchObjectsResult:
    objects: tuple[dict[str, Any], ...]
    returned_count: int
    truncated: bool
    truncation_reason: TruncationReason | None
    elapsed_ms: int
    result_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "objects": list(self.objects),
            "returned_count": self.returned_count,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "elapsed_ms": self.elapsed_ms,
            "result_bytes": self.result_bytes,
        }


@dataclass(frozen=True, slots=True)
class FormattedQueryResult:
    columns: tuple[dict[str, str], ...]
    rows: tuple[tuple[Any, ...], ...]
    returned_rows: int
    truncated: bool
    truncation_reason: TruncationReason | None
    elapsed_ms: int
    result_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
            "returned_rows": self.returned_rows,
            "truncated": self.truncated,
            "truncation_reason": self.truncation_reason,
            "elapsed_ms": self.elapsed_ms,
            "result_bytes": self.result_bytes,
        }
