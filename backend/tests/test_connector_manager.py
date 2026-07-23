import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest

from context_router.database import (
    Column,
    ConnectorCapabilities,
    ConnectorManager,
    ConnectorManagerError,
    ConnectorRegistry,
    ConnectorSpec,
    QueryResult,
    SearchObjectsResult,
)


class FakeConnector:
    def __init__(self, identifier: int, *, ping_error: bool = False) -> None:
        self.identifier = identifier
        self.ping_error = ping_error
        self.ping_calls = 0
        self.close_calls = 0

    @property
    def engine(self) -> str:
        return "clickhouse"

    @property
    def capabilities(self) -> ConnectorCapabilities:
        return ConnectorCapabilities(execute_readonly_query=True)

    def ping(self) -> None:
        self.ping_calls += 1
        if self.ping_error:
            raise OSError("secret DSN must not escape")

    def discover_databases(self):
        return []

    def search_objects(self, request, policy) -> SearchObjectsResult:
        return SearchObjectsResult(objects=[])

    def execute_query(self, sql, policy) -> QueryResult:
        return QueryResult(columns=[Column("value", "Int32")], rows=[(1,)])

    def close(self) -> None:
        self.close_calls += 1


class FakeFactory:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.created: list[FakeConnector] = []
        self.fail_versions: set[int] = set()
        self.wait_event: threading.Event | None = None
        self.started_event: threading.Event | None = None

    def __call__(self, spec: ConnectorSpec) -> FakeConnector:
        if self.started_event is not None:
            self.started_event.set()
        if self.wait_event is not None:
            assert self.wait_event.wait(timeout=2)
        with self.lock:
            connector = FakeConnector(
                len(self.created) + 1,
                ping_error=spec.config_version in self.fail_versions,
            )
            self.created.append(connector)
            return connector


def make_spec(
    *,
    source: str = "source-1",
    version: int = 1,
    database: str = "database-1",
    updated_at: datetime | None = None,
) -> ConnectorSpec:
    return ConnectorSpec(
        data_source_id=source,
        config_version=version,
        database_id=database,
        database_updated_at=updated_at or datetime(2026, 7, 22, tzinfo=UTC),
        engine="clickhouse",
        remote_name=database,
        connection_config={"host": "localhost", "password": "secret"},
    )


def make_manager(
    factory: FakeFactory,
    *,
    max_cached: int = 16,
    max_concurrency: int = 20,
) -> ConnectorManager:
    registry = ConnectorRegistry()
    registry.register("clickhouse", factory, ConnectorCapabilities(execute_readonly_query=True))
    return ConnectorManager(
        registry,
        max_cached_connectors=max_cached,
        max_concurrency_per_source=max_concurrency,
    )


def test_manager_is_lazy_reuses_connector_and_closes_idempotently() -> None:
    factory = FakeFactory()
    manager = make_manager(factory)
    assert manager.cached_connector_count == 0

    with manager.lease(make_spec()) as first:
        assert first.identifier == 1
        assert manager.active_lease_count == 1
    with manager.lease(make_spec()) as second:
        assert second is first

    assert len(factory.created) == 1
    assert factory.created[0].ping_calls == 1
    manager.close_all()
    manager.close_all()
    assert factory.created[0].close_calls == 1


def test_manager_single_flight_initializes_once_for_concurrent_first_use() -> None:
    factory = FakeFactory()
    factory.wait_event = threading.Event()
    factory.started_event = threading.Event()
    manager = make_manager(factory)
    spec = make_spec()

    def get_connector_id() -> int:
        with manager.lease(spec) as connector:
            return connector.identifier

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(get_connector_id) for _ in range(20)]
        assert factory.started_event.wait(timeout=2)
        time.sleep(0.05)
        factory.wait_event.set()
        identifiers = [future.result(timeout=2) for future in futures]

    assert identifiers == [1] * 20
    assert len(factory.created) == 1
    manager.close_all()


def test_manager_single_flight_shares_initialization_failure() -> None:
    factory = FakeFactory()
    factory.fail_versions.add(1)
    factory.wait_event = threading.Event()
    factory.started_event = threading.Event()
    manager = make_manager(factory)
    spec = make_spec()

    def try_lease() -> str:
        try:
            with manager.lease(spec):
                return "unexpected"
        except ConnectorManagerError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(try_lease) for _ in range(20)]
        assert factory.started_event.wait(timeout=2)
        time.sleep(0.05)
        factory.wait_event.set()
        codes = [future.result(timeout=2) for future in futures]

    assert codes == ["connection_failed"] * 20
    assert len(factory.created) == 1


def test_manager_does_not_cache_connector_that_fails_ping() -> None:
    factory = FakeFactory()
    factory.fail_versions.add(1)
    manager = make_manager(factory)

    for _ in range(2):
        with pytest.raises(ConnectorManagerError) as failed:
            with manager.lease(make_spec()):
                pass
        assert failed.value.code == "connection_failed"
        assert "secret" not in str(failed.value)

    assert len(factory.created) == 2
    assert all(connector.close_calls == 1 for connector in factory.created)
    assert manager.cached_connector_count == 0


def test_config_update_is_make_before_break_and_old_lease_finishes() -> None:
    factory = FakeFactory()
    manager = make_manager(factory)

    with manager.lease(make_spec(version=1)) as old_connector:
        with manager.lease(make_spec(version=2)) as new_connector:
            assert new_connector is not old_connector
            assert old_connector.close_calls == 0
        assert old_connector.close_calls == 0

    assert old_connector.close_calls == 1
    assert new_connector.close_calls == 0
    manager.close_all()
    assert new_connector.close_calls == 1


def test_failed_new_config_never_falls_back_to_old_connector() -> None:
    factory = FakeFactory()
    manager = make_manager(factory)
    old_spec = make_spec(version=1)
    with manager.lease(old_spec):
        pass
    factory.fail_versions.add(2)

    with pytest.raises(ConnectorManagerError):
        with manager.lease(make_spec(version=2)):
            pass
    with pytest.raises(ConnectorManagerError, match="stale"):
        with manager.lease(old_spec):
            pass

    assert len(factory.created) == 2
    manager.close_all()


def test_invalidate_waits_for_active_lease_before_closing() -> None:
    factory = FakeFactory()
    manager = make_manager(factory)

    with manager.lease(make_spec()) as connector:
        manager.invalidate_source("source-1")
        assert connector.close_calls == 0
        assert manager.cached_connector_count == 0

    assert connector.close_calls == 1


def test_lru_evicts_only_idle_connectors() -> None:
    factory = FakeFactory()
    manager = make_manager(factory, max_cached=2)
    specs = [make_spec(source=f"source-{index}") for index in range(3)]

    for spec in specs:
        with manager.lease(spec):
            pass
        time.sleep(0.001)

    assert manager.cached_connector_count == 2
    assert factory.created[0].close_calls == 1
    assert factory.created[1].close_calls == 0
    assert factory.created[2].close_calls == 0
    manager.close_all()


def test_manager_limits_concurrent_leases_per_source() -> None:
    factory = FakeFactory()
    manager = make_manager(factory, max_concurrency=2)
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0

    def query() -> None:
        nonlocal active, maximum_active
        with manager.lease(make_spec()):
            with state_lock:
                active += 1
                maximum_active = max(maximum_active, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(lambda _: query(), range(6)))

    assert maximum_active == 2
    manager.close_all()


def test_database_updated_at_retires_previous_target() -> None:
    factory = FakeFactory()
    manager = make_manager(factory)
    first_time = datetime(2026, 7, 22, tzinfo=UTC)
    with manager.lease(make_spec(updated_at=first_time)) as first:
        pass
    with manager.lease(make_spec(updated_at=first_time + timedelta(seconds=1))) as second:
        pass

    assert first is not second
    assert first.close_calls == 1
    manager.close_all()


def test_close_all_marks_active_connector_retiring() -> None:
    factory = FakeFactory()
    manager = make_manager(factory)

    with manager.lease(make_spec()) as connector:
        manager.close_all()
        assert connector.close_calls == 0
        with pytest.raises(ConnectorManagerError):
            with manager.lease(make_spec()):
                pass

    assert connector.close_calls == 1
