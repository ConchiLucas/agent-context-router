from datetime import UTC, datetime

import pytest

from context_router.database import (
    Column,
    ConnectorCapabilities,
    ConnectorRegistry,
    ConnectorRegistryError,
    ConnectorSpec,
    QueryResult,
    SearchObjectsResult,
)


class FakeConnector:
    def __init__(self, engine: str = "clickhouse") -> None:
        self._engine = engine
        self.closed = False

    @property
    def engine(self) -> str:
        return self._engine

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(execute_readonly_query=True)

    def ping(self) -> None:
        return None

    def discover_databases(self):
        return []

    def search_objects(self, request, policy) -> SearchObjectsResult:
        return SearchObjectsResult(objects=[])

    def execute_query(self, sql, policy) -> QueryResult:
        return QueryResult(columns=[Column("value", "Int32")], rows=[(1,)])

    def close(self) -> None:
        self.closed = True


def make_spec(config: dict[str, object] | None = None) -> ConnectorSpec:
    return ConnectorSpec(
        data_source_id="source-1",
        config_version=1,
        database_id="database-1",
        database_updated_at=datetime.now(UTC),
        engine="CLICKHOUSE",
        remote_name="analytics",
        connection_config=config or {"host": "localhost", "password": "secret"},
    )


def test_connector_spec_normalizes_engine_and_hides_credentials() -> None:
    config: dict[str, object] = {"host": "localhost", "password": "secret"}
    spec = make_spec(config)
    config["password"] = "changed"

    assert spec.engine == "clickhouse"
    assert spec.connection_config["password"] == "secret"
    assert "secret" not in repr(spec)
    assert spec.cache_key.data_source_id == "source-1"


def test_registry_exposes_static_capabilities_and_creates_connector() -> None:
    registry = ConnectorRegistry()
    capabilities = ConnectorCapabilities(
        discover_databases=True,
        search_tables=True,
        execute_readonly_query=True,
    )
    connector = FakeConnector()
    registry.register("ClickHouse", lambda spec: connector, capabilities)

    assert registry.registered_engines() == ("clickhouse",)
    assert registry.capabilities("CLICKHOUSE") == capabilities
    assert registry.create(make_spec()) is connector


def test_registry_rejects_duplicate_and_unsupported_engines() -> None:
    registry = ConnectorRegistry()
    registry.register("clickhouse", lambda spec: FakeConnector(), ConnectorCapabilities())

    with pytest.raises(ConnectorRegistryError, match="already registered") as duplicate:
        registry.register("CLICKHOUSE", lambda spec: FakeConnector(), ConnectorCapabilities())
    assert duplicate.value.code == "duplicate_connector"

    with pytest.raises(ConnectorRegistryError) as unsupported:
        registry.capabilities("oracle")
    assert unsupported.value.code == "engine_not_supported"


def test_registry_closes_connector_when_factory_returns_wrong_engine() -> None:
    registry = ConnectorRegistry()
    connector = FakeConnector(engine="mysql")
    registry.register("clickhouse", lambda spec: connector, ConnectorCapabilities())

    with pytest.raises(ConnectorRegistryError) as mismatch:
        registry.create(make_spec())

    assert mismatch.value.code == "connector_engine_mismatch"
    assert connector.closed is True
