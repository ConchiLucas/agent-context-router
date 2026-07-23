from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import (
    ConnectorCapabilities,
    ConnectorSpec,
    DiscoveredDatabase,
    EffectiveQueryPolicy,
    QueryResult,
    SearchObjectsRequest,
    SearchObjectsResult,
)


@runtime_checkable
class DatabaseConnector(Protocol):
    @property
    def engine(self) -> str: ...

    @property
    def capabilities(self) -> ConnectorCapabilities: ...

    def ping(self) -> None: ...

    def discover_databases(self) -> list[DiscoveredDatabase]: ...

    def search_objects(
        self,
        request: SearchObjectsRequest,
        policy: EffectiveQueryPolicy,
    ) -> SearchObjectsResult: ...

    def execute_query(
        self,
        sql: str,
        policy: EffectiveQueryPolicy,
    ) -> QueryResult: ...

    def close(self) -> None: ...


class ConnectorFactory(Protocol):
    def __call__(self, spec: ConnectorSpec) -> DatabaseConnector: ...
