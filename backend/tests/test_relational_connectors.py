from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import psycopg
import pymysql
import pytest

from context_router.database.connectors.mysql import MySQLConnector
from context_router.database.connectors.postgresql import PostgreSQLConnector
from context_router.database.errors import DatabaseConnectorError
from context_router.database.models import (
    ConnectorSpec,
    DatabaseObjectType,
    EffectiveQueryPolicy,
    SearchObjectsRequest,
)


def _spec(engine: str, remote_name: str = "app") -> ConnectorSpec:
    return ConnectorSpec(
        data_source_id="source-1",
        config_version=1,
        database_id="database-1",
        database_updated_at=datetime.now(UTC),
        engine=engine,
        remote_name=remote_name,
        connection_config={
            "host": "db.internal",
            "port": 5432 if engine == "postgresql" else 3306,
            "username": "reader",
            "password": "private",
        },
    )


def _policy(engine: str, *, max_rows: int = 2) -> EffectiveQueryPolicy:
    return EffectiveQueryPolicy(
        engine=engine,
        current_database="app",
        readonly=True,
        allowed_schemas=("public",) if engine == "postgresql" else (),
        max_rows=max_rows,
        max_result_bytes=10_000,
        query_timeout_ms=1_250,
    )


def test_postgresql_query_uses_target_database_readonly_transaction_and_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakePostgresConnection()
    captured: dict[str, Any] = {}

    def connect(**kwargs: Any) -> FakePostgresConnection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(psycopg, "connect", connect)
    connector = PostgreSQLConnector(_spec("postgresql"))

    result = connector.execute_query("SELECT id FROM public.events", _policy("postgresql"))

    assert captured["dbname"] == "app"
    assert captured["user"] == "reader"
    assert connection.executed[0] == ("SET TRANSACTION READ ONLY", None)
    assert connection.executed[1] == (
        "SELECT set_config('statement_timeout', %s, true)",
        ("1250",),
    )
    assert connection.named_cursor is True
    assert connection.cursor_statements == ["SELECT id FROM public.events"]
    assert result.columns[0].name == "id"
    assert len(result.rows) == 3
    assert result.truncated is True


def test_postgresql_catalog_uses_bound_glob_schema_and_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakePostgresConnection(catalog_rows=[("events", "public", "table")])
    monkeypatch.setattr(psycopg, "connect", lambda **_: connection)
    connector = PostgreSQLConnector(_spec("postgresql"))

    result = connector.search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            glob="event*",
            schema="public",
            limit=10,
        ),
        _policy("postgresql"),
    )

    catalog_statement, params = connection.executed[-1]
    assert "relation.relname ~ %s" in catalog_statement
    assert params == ["^event.*$", ["r", "p", "f"], "public", ["public"], 11]
    assert result.objects[0].name == "events"


@pytest.mark.parametrize("engine", ["mysql", "mariadb"])
def test_mysql_family_query_uses_server_timeout_readonly_transaction_and_streaming(
    engine: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeMySQLConnection()
    captured: dict[str, Any] = {}

    def connect(**kwargs: Any) -> FakeMySQLConnection:
        captured.update(kwargs)
        return connection

    monkeypatch.setattr(pymysql, "connect", connect)
    connector = MySQLConnector(_spec(engine))

    result = connector.execute_query("SELECT id FROM events", _policy(engine))

    expected_timeout = (
        ("SET SESSION MAX_EXECUTION_TIME = %s", (1_250,))
        if engine == "mysql"
        else ("SET SESSION max_statement_time = %s", (1.25,))
    )
    assert connection.executed[:3] == [
        expected_timeout,
        ("START TRANSACTION READ ONLY", None),
        ("SELECT id FROM events", None),
    ]
    assert captured["database"] == "app"
    assert captured["cursorclass"] is pymysql.cursors.SSCursor
    assert connection.rolled_back is True
    assert connection.closed is True
    assert len(result.rows) == 3
    assert result.truncated is True


@pytest.mark.parametrize(
    ("error_code", "expected_code", "expected_message"),
    [
        (3024, "query_timeout", "MySQL 查询超时"),
        (1969, "query_timeout", "MySQL 查询超时"),
        (1317, "query_cancelled", "MySQL 查询已取消"),
    ],
)
def test_mysql_family_maps_query_interruptions_to_stable_errors(
    error_code: int,
    expected_code: str,
    expected_message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = FakeMySQLConnection(
        execute_error=pymysql.err.OperationalError(
            error_code,
            "private SQL and connection details",
        )
    )
    monkeypatch.setattr(pymysql, "connect", lambda **_: connection)
    connector = MySQLConnector(_spec("mysql"))

    with pytest.raises(DatabaseConnectorError) as captured:
        connector.execute_query("SELECT id FROM events", _policy("mysql"))

    assert captured.value.code == expected_code
    assert str(captured.value) == expected_message


class FakeResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class FakePostgresCursor:
    def __init__(self, connection: FakePostgresConnection) -> None:
        self._connection = connection
        self.description = [SimpleNamespace(name="id", type_code=23)]

    def __enter__(self) -> FakePostgresCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self._connection.cursor_statements.append(statement)

    def fetchmany(self, _: int) -> list[tuple[int]]:
        return [(1,), (2,), (3,)]


class FakePostgresConnection:
    def __init__(self, catalog_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.catalog_rows = catalog_rows or []
        self.executed: list[tuple[Any, Any]] = []
        self.cursor_statements: list[str] = []
        self.named_cursor = False

    def __enter__(self) -> FakePostgresConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def transaction(self):
        return nullcontext()

    def execute(self, statement: Any, params: Any = None) -> FakeResult:
        self.executed.append((statement, params))
        return FakeResult(self.catalog_rows)

    def cursor(self, *, name: str | None = None) -> FakePostgresCursor:
        self.named_cursor = name is not None
        return FakePostgresCursor(self)


class FakeMySQLCursor:
    def __init__(self, connection: FakeMySQLConnection) -> None:
        self._connection = connection
        self.description = [("id", 3)]

    def __enter__(self) -> FakeMySQLCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: Any = None) -> None:
        self._connection.executed.append((statement, params))
        if statement == "SELECT id FROM events" and self._connection.execute_error is not None:
            raise self._connection.execute_error

    def fetchmany(self, _: int) -> list[tuple[int]]:
        return [(1,), (2,), (3,)]


class FakeMySQLConnection:
    def __init__(self, execute_error: pymysql.MySQLError | None = None) -> None:
        self.executed: list[tuple[str, Any]] = []
        self.execute_error = execute_error
        self.rolled_back = False
        self.closed = False

    def cursor(self) -> FakeMySQLCursor:
        return FakeMySQLCursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True
