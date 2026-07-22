from datetime import UTC, datetime

from context_router.repositories.data_source_repository import DataSourceRecord
from context_router.services.database_discovery import discover_databases


class FakeCursor:
    def __init__(self) -> None:
        self.statement = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statement = statement

    def fetchall(self) -> list[tuple[str]]:
        return [("orders",), ("mysql",), ("information_schema",)]


class FakeConnection:
    def __init__(self) -> None:
        self.cursor_instance = FakeCursor()
        self.closed = False

    def cursor(self) -> FakeCursor:
        return self.cursor_instance

    def close(self) -> None:
        self.closed = True


def test_mysql_discovery_lists_visible_databases_and_marks_system_names(monkeypatch) -> None:
    connection = FakeConnection()
    captured: dict[str, object] = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr("pymysql.connect", fake_connect)
    now = datetime.now(UTC)
    source = DataSourceRecord(
        id="source-1",
        name="MySQL",
        category="本机电脑",
        engine="mysql",
        description="",
        connection_config={
            "host": "mysql.example.com",
            "port": 3307,
            "username": "reader",
            "password": "secret",
        },
        enabled=True,
        config_version=1,
        database_count=0,
        project_count=0,
        created_at=now,
        updated_at=now,
    )

    databases = discover_databases(source)

    assert captured["host"] == "mysql.example.com"
    assert captured["port"] == 3307
    assert captured["user"] == "reader"
    assert captured["password"] == "secret"
    assert connection.cursor_instance.statement == "SHOW DATABASES"
    assert connection.closed is True
    assert [database.name for database in databases] == [
        "information_schema",
        "mysql",
        "orders",
    ]
    assert databases[0].system_database is True
    assert databases[1].system_database is True
    assert databases[2].system_database is False


def test_postgresql_discovery_lists_non_template_databases(monkeypatch) -> None:
    connection = FakeConnection()
    connection.cursor_instance.fetchall = lambda: [
        ("context_router",),
        ("postgres",),
        ("task_board",),
    ]
    captured: dict[str, object] = {}

    def fake_connect(**kwargs):
        captured.update(kwargs)
        return connection

    monkeypatch.setattr("psycopg.connect", fake_connect)
    now = datetime.now(UTC)
    source = DataSourceRecord(
        id="source-pg",
        name="PostgreSQL",
        category="本机电脑",
        engine="postgresql",
        description="",
        connection_config={
            "host": "postgres.example.com",
            "port": 5544,
            "username": "postgres",
            "password": "secret",
            "database": "context_router",
        },
        enabled=True,
        config_version=1,
        database_count=0,
        project_count=0,
        created_at=now,
        updated_at=now,
    )

    databases = discover_databases(source)

    assert captured["host"] == "postgres.example.com"
    assert captured["port"] == 5544
    assert captured["user"] == "postgres"
    assert captured["dbname"] == "context_router"
    assert "FROM pg_database" in connection.cursor_instance.statement
    assert connection.closed is True
    assert [database.name for database in databases] == [
        "context_router",
        "postgres",
        "task_board",
    ]
    assert databases[0].system_database is False
    assert databases[1].system_database is True
