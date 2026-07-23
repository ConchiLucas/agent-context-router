from datetime import UTC, datetime

import pytest

from context_router.database.connectors.clickhouse import ClickHouseConnector
from context_router.database.errors import DatabaseConnectorError
from context_router.database.models import (
    ConnectorSpec,
    DatabaseObjectType,
    EffectiveQueryPolicy,
    SearchDetail,
    SearchObjectsRequest,
    TruncationReason,
)


class FakeType:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.result_rows = rows


class FakeStreamSource:
    column_names = ("id", "name")
    column_types = (FakeType("UInt64"), FakeType("String"))


class FakeStream:
    source = FakeStreamSource()

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.closed = False

    def __enter__(self):
        return iter(self._rows)

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.closed = True


class FakeClickHouseClient:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.queries: list[tuple[str, dict[str, object] | None, dict[str, object]]] = []
        self.stream_queries: list[tuple[str, dict[str, object]]] = []
        self.stream_error: Exception | None = None
        self.closed = False

    def command(self, statement: str) -> int:
        self.commands.append(statement)
        return 1

    def query(self, statement, parameters=None, settings=None, **kwargs):
        self.queries.append((statement, parameters, settings or {}))
        if "FROM system.databases" in statement:
            return FakeResult([("analytics",), ("system",)])
        if "FROM system.tables" in statement:
            return FakeResult(
                [
                    (
                        "event_daily",
                        "analytics",
                        "MergeTree",
                        100,
                        2048,
                        "events",
                        "day",
                        "day",
                        "toYYYYMM(day)",
                    )
                ]
            )
        if "FROM system.columns" in statement:
            return FakeResult(
                [
                    (
                        "event_daily",
                        "day",
                        "Date",
                        "",
                        "",
                        "event day",
                        True,
                        True,
                        True,
                    )
                ]
            )
        return FakeResult([])

    def query_rows_stream(self, statement, settings=None, **kwargs):
        self.stream_queries.append((statement, settings or {}))
        if self.stream_error is not None:
            raise self.stream_error
        return FakeStream([(1, "a"), (2, "b"), (3, "c")])

    def close(self) -> None:
        self.closed = True


def connector_spec(**config: object) -> ConnectorSpec:
    return ConnectorSpec(
        data_source_id="source-1",
        config_version=2,
        database_id="database-1",
        database_updated_at=datetime.now(UTC),
        engine="clickhouse",
        remote_name="analytics",
        connection_config={
            "host": "clickhouse.example.com",
            "port": 8443,
            "username": "reader",
            "password": "private",
            "secure": True,
            "verify": True,
            **config,
        },
    )


def query_policy(**changes: object) -> EffectiveQueryPolicy:
    values = {
        "engine": "clickhouse",
        "current_database": "analytics",
        "readonly": True,
        "allowed_schemas": (),
        "max_rows": 2,
        "max_result_bytes": 50_000,
        "query_timeout_ms": 5_000,
    }
    values.update(changes)
    return EffectiveQueryPolicy(**values)  # type: ignore[arg-type]


def test_clickhouse_connector_uses_target_database_and_closes(monkeypatch) -> None:
    client = FakeClickHouseClient()
    captured: dict[str, object] = {}

    def fake_get_client(**kwargs):
        captured.update(kwargs)
        return client

    monkeypatch.setattr("clickhouse_connect.get_client", fake_get_client)

    connector = ClickHouseConnector(connector_spec())
    connector.ping()
    databases = connector.discover_databases()
    connector.close()
    connector.close()

    assert captured["database"] == "analytics"
    assert captured["secure"] is True
    assert captured["verify"] is True
    assert captured["password"] == "private"
    assert client.commands == ["SELECT 1"]
    assert [database.name for database in databases] == ["analytics", "system"]
    assert databases[1].system_database is True
    assert client.closed is True


def test_clickhouse_table_search_uses_parameters_and_progressive_details(monkeypatch) -> None:
    client = FakeClickHouseClient()
    monkeypatch.setattr("clickhouse_connect.get_client", lambda **kwargs: client)
    connector = ClickHouseConnector(connector_spec())

    result = connector.search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            glob="event_*",
            detail=SearchDetail.FULL,
            limit=10,
        ),
        query_policy(),
    )

    item = list(result.objects)[0]
    assert item.name == "event_daily"
    assert item.kind == "table"
    assert item.details["estimated_rows"] == 100
    assert item.details["columns"][0]["name"] == "day"
    table_query = client.queries[0]
    assert "{database:String}" in table_query[0]
    assert table_query[1]["database"] == "analytics"
    assert table_query[1]["pattern"] == "^event_.*$"


def test_clickhouse_query_injects_readonly_resource_limits(monkeypatch) -> None:
    client = FakeClickHouseClient()
    monkeypatch.setattr("clickhouse_connect.get_client", lambda **kwargs: client)
    connector = ClickHouseConnector(connector_spec())

    result = connector.execute_query("SELECT id, name FROM events", query_policy())

    assert [column.name for column in result.columns] == ["id", "name"]
    assert list(result.rows) == [(1, "a"), (2, "b"), (3, "c")]
    assert result.truncated is True
    assert result.truncation_reason is TruncationReason.ROWS
    settings = client.stream_queries[0][1]
    assert settings["readonly"] == 1
    assert settings["max_result_rows"] == 3
    assert settings["max_execution_time"] == 5.0
    assert settings["max_threads"] == 4
    assert settings["max_rows_to_read"] == 10_000_000
    assert len(settings["query_id"]) == 32


@pytest.mark.parametrize(
    ("server_code", "server_name", "expected_code", "expected_message"),
    [
        (159, "TIMEOUT_EXCEEDED", "query_timeout", "ClickHouse 查询超时"),
        (394, "QUERY_WAS_CANCELLED", "query_cancelled", "ClickHouse 查询已取消"),
    ],
)
def test_clickhouse_query_maps_server_interruption_to_stable_error(
    monkeypatch,
    server_code: int,
    server_name: str,
    expected_code: str,
    expected_message: str,
) -> None:
    class ServerInterruptionError(RuntimeError):
        code = server_code
        name = server_name

    client = FakeClickHouseClient()
    client.stream_error = ServerInterruptionError("private SQL and connection details")
    monkeypatch.setattr("clickhouse_connect.get_client", lambda **kwargs: client)
    connector = ClickHouseConnector(connector_spec())

    with pytest.raises(DatabaseConnectorError) as captured:
        connector.execute_query("SELECT sleepEachRow(1)", query_policy(query_timeout_ms=100))

    assert captured.value.code == expected_code
    assert str(captured.value) == expected_message


def test_clickhouse_connection_error_does_not_expose_driver_message(monkeypatch) -> None:
    def fail(**kwargs):
        raise RuntimeError("https://reader:private@clickhouse.example.com")

    monkeypatch.setattr("clickhouse_connect.get_client", fail)

    with pytest.raises(DatabaseConnectorError) as captured:
        ClickHouseConnector(connector_spec())

    assert captured.value.code == "connection_failed"
    assert "private" not in str(captured.value)
