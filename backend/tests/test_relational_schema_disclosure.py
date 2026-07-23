from __future__ import annotations

from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Any

import psycopg
import pymysql
import pytest

from context_router.database.connectors.mysql import MySQLConnector
from context_router.database.connectors.postgresql import PostgreSQLConnector
from context_router.database.models import (
    ConnectorSpec,
    DatabaseObjectType,
    EffectiveQueryPolicy,
    SearchDetail,
    SearchObjectsRequest,
)


def _spec(engine: str) -> ConnectorSpec:
    return ConnectorSpec(
        data_source_id=f"{engine}-source",
        config_version=1,
        database_id=f"{engine}-database",
        database_updated_at=datetime.now(UTC),
        engine=engine,
        remote_name="app",
        connection_config={
            "host": "db.internal",
            "port": 5432 if engine == "postgresql" else 3306,
            "username": "reader",
            "password": "private",
        },
    )


def _policy(engine: str) -> EffectiveQueryPolicy:
    return EffectiveQueryPolicy(
        engine=engine,
        current_database="app",
        readonly=True,
        allowed_schemas=("public",) if engine == "postgresql" else (),
        max_rows=100,
        max_result_bytes=100_000,
        query_timeout_ms=1_250,
    )


def test_postgresql_relation_progressive_disclosure_uses_fixed_batch_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names_connection = RecordingPostgresConnection(
        [("FROM pg_catalog.pg_class AS relation", [("events", "public", "table")])]
    )
    monkeypatch.setattr(psycopg, "connect", lambda **_: names_connection)
    names = PostgreSQLConnector(_spec("postgresql")).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            detail=SearchDetail.NAMES,
        ),
        _policy("postgresql"),
    )
    assert list(names.objects)[0].as_mapping() == {
        "name": "events",
        "schema": "public",
        "kind": "table",
    }

    summary_connection = RecordingPostgresConnection(
        [
            (
                "FROM pg_catalog.pg_class AS relation",
                [("events", "public", "table", 1200, 8192, "event stream")],
            )
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda **_: summary_connection)
    summary = PostgreSQLConnector(_spec("postgresql")).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            detail=SearchDetail.SUMMARY,
        ),
        _policy("postgresql"),
    )
    assert list(summary.objects)[0].details == {
        "estimated_rows": 1200,
        "estimated_bytes": 8192,
        "comment": "event stream",
    }
    view_connection = RecordingPostgresConnection(
        [
            (
                "FROM pg_catalog.pg_class AS relation",
                [("recent_events", "public", "view", -1, 0, "recent event view")],
            )
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda **_: view_connection)
    view_summary = PostgreSQLConnector(_spec("postgresql")).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.VIEW,
            detail=SearchDetail.SUMMARY,
        ),
        _policy("postgresql"),
    )
    view = list(view_summary.objects)[0]
    assert view.kind == "view"
    assert view.details == {
        "estimated_rows": -1,
        "estimated_bytes": 0,
        "comment": "recent event view",
    }

    full_connection = RecordingPostgresConnection(
        [
            (
                "FROM pg_catalog.pg_class AS relation",
                [
                    ("events", "public", "table", 1200, 8192, "event stream"),
                    ("users", "public", "table", 25, 4096, None),
                ],
            ),
            (
                "JOIN information_schema.columns AS column_info",
                [
                    ("public", "events", "id", "bigint", "NO", None, 1, None, 64, "NEVER"),
                    ("public", "users", "email", "text", "NO", None, 1, None, None, "NEVER"),
                ],
            ),
            (
                "JOIN information_schema.table_constraints AS constraint_info",
                [
                    ("public", "events", "events_pkey", "PRIMARY KEY", "id", 1),
                    ("public", "users", "users_email_key", "UNIQUE", "email", 1),
                ],
            ),
            (
                "JOIN pg_catalog.pg_index AS index_info",
                [
                    (
                        "public",
                        "events",
                        "events_pkey",
                        "btree",
                        True,
                        True,
                        "CREATE UNIQUE INDEX events_pkey ON public.events USING btree (id)",
                        None,
                    ),
                    (
                        "public",
                        "users",
                        "users_email_key",
                        "btree",
                        True,
                        False,
                        "CREATE UNIQUE INDEX users_email_key ON public.users USING btree (email)",
                        None,
                    ),
                ],
            ),
        ]
    )
    monkeypatch.setattr(psycopg, "connect", lambda **_: full_connection)
    full = PostgreSQLConnector(_spec("postgresql")).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            detail=SearchDetail.FULL,
        ),
        _policy("postgresql"),
    )

    full_objects = list(full.objects)
    assert full_objects[0].details["columns"] == [
        {
            "name": "id",
            "type": "bigint",
            "nullable": False,
            "default": None,
            "ordinal_position": 1,
            "max_length": None,
            "numeric_precision": 64,
            "generated": False,
        }
    ]
    assert full_objects[0].details["keys"] == [
        {"name": "events_pkey", "type": "PRIMARY KEY", "columns": ["id"]}
    ]
    assert full_objects[0].details["indexes"][0]["name"] == "events_pkey"
    assert full_objects[1].details["columns"][0]["name"] == "email"
    catalog_statements = full_connection.catalog_statements
    assert len(catalog_statements) == 4
    assert all(
        "events" not in statement and "users" not in statement for statement in catalog_statements
    )
    assert full_connection.executed[:2] == [
        ("SET TRANSACTION READ ONLY", None),
        ("SELECT set_config('statement_timeout', %s, true)", ("1250",)),
    ]
    assert any(
        params is not None and "events" in params and "users" in params
        for _, params in full_connection.executed
    )
    indexes_statement = next(
        statement
        for statement in catalog_statements
        if "JOIN pg_catalog.pg_index AS index_info" in statement
    )
    assert indexes_statement.count("ON index_relation.oid = index_info.indexrelid") == 1


def test_postgresql_column_and_index_details_are_layered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    column_rows = {
        SearchDetail.NAMES: [("id", "public", "column")],
        SearchDetail.SUMMARY: [("id", "public", "column", "events", "bigint", "NO")],
        SearchDetail.FULL: [
            ("id", "public", "column", "events", "bigint", "NO", None, 1, None, 64, "NEVER")
        ],
    }
    expected_column_details = {
        SearchDetail.NAMES: {},
        SearchDetail.SUMMARY: {"table": "events", "type": "bigint", "nullable": False},
        SearchDetail.FULL: {
            "table": "events",
            "type": "bigint",
            "nullable": False,
            "default": None,
            "ordinal_position": 1,
            "max_length": None,
            "numeric_precision": 64,
            "generated": False,
        },
    }
    for detail in SearchDetail:
        connection = RecordingPostgresConnection(
            [("column_info.column_name ~ %s", column_rows[detail])]
        )
        monkeypatch.setattr(psycopg, "connect", lambda value=connection, **_: value)
        result = PostgreSQLConnector(_spec("postgresql")).search_objects(
            SearchObjectsRequest(
                object_type=DatabaseObjectType.COLUMN,
                table="events",
                detail=detail,
            ),
            _policy("postgresql"),
        )
        assert list(result.objects)[0].details == expected_column_details[detail]

    index_rows = {
        SearchDetail.NAMES: [("events_pkey", "public", "index")],
        SearchDetail.SUMMARY: [("events_pkey", "public", "index", "events", "btree", True, True)],
        SearchDetail.FULL: [
            (
                "events_pkey",
                "public",
                "index",
                "events",
                "btree",
                True,
                True,
                "CREATE UNIQUE INDEX events_pkey ON public.events USING btree (id)",
                None,
            )
        ],
    }
    for detail in SearchDetail:
        responses: list[tuple[str, list[tuple[Any, ...]]]] = [
            ("index_relation.relname ~ %s", index_rows[detail])
        ]
        if detail is SearchDetail.FULL:
            responses.append(
                ("index_column.position", [("public", "events", "events_pkey", 1, "id")])
            )
        connection = RecordingPostgresConnection(responses)
        monkeypatch.setattr(psycopg, "connect", lambda value=connection, **_: value)
        result = PostgreSQLConnector(_spec("postgresql")).search_objects(
            SearchObjectsRequest(
                object_type=DatabaseObjectType.INDEX,
                table="events",
                detail=detail,
            ),
            _policy("postgresql"),
        )
        details = list(result.objects)[0].details
        if detail is SearchDetail.NAMES:
            assert details == {}
        else:
            assert details["table"] == "events"
            assert details["type"] == "btree"
            assert details["unique"] is True
            assert details["primary"] is True
            if detail is SearchDetail.SUMMARY:
                assert "definition" not in details
                assert "columns" not in details
            else:
                assert details["columns"] == [{"position": 1, "expression": "id"}]


@pytest.mark.parametrize("engine", ["mysql", "mariadb"])
def test_mysql_family_relation_progressive_disclosure_uses_fixed_batch_count(
    engine: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    names_connection = RecordingMySQLConnection(
        [("FROM information_schema.TABLES AS relation", [("events", "app", "table")])]
    )
    monkeypatch.setattr(pymysql, "connect", lambda **_: names_connection)
    names = MySQLConnector(_spec(engine)).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            detail=SearchDetail.NAMES,
        ),
        _policy(engine),
    )
    assert list(names.objects)[0].as_mapping() == {
        "name": "events",
        "schema": "app",
        "kind": "table",
    }

    summary_connection = RecordingMySQLConnection(
        [
            (
                "FROM information_schema.TABLES AS relation",
                [("events", "app", "table", "InnoDB", 1200, 12288, "event stream")],
            )
        ]
    )
    monkeypatch.setattr(pymysql, "connect", lambda **_: summary_connection)
    summary = MySQLConnector(_spec(engine)).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            detail=SearchDetail.SUMMARY,
        ),
        _policy(engine),
    )
    assert list(summary.objects)[0].details == {
        "engine": "InnoDB",
        "estimated_rows": 1200,
        "estimated_bytes": 12288,
        "comment": "event stream",
    }
    view_connection = RecordingMySQLConnection(
        [
            (
                "FROM information_schema.TABLES AS relation",
                [("recent_events", "app", "view", None, None, 0, "recent event view")],
            )
        ]
    )
    monkeypatch.setattr(pymysql, "connect", lambda **_: view_connection)
    view_summary = MySQLConnector(_spec(engine)).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.VIEW,
            detail=SearchDetail.SUMMARY,
        ),
        _policy(engine),
    )
    view = list(view_summary.objects)[0]
    assert view.kind == "view"
    assert view.details == {
        "engine": None,
        "estimated_rows": None,
        "estimated_bytes": 0,
        "comment": "recent event view",
    }

    full_connection = RecordingMySQLConnection(
        [
            (
                "FROM information_schema.TABLES AS relation",
                [
                    ("events", "app", "table", "InnoDB", 1200, 12288, "event stream"),
                    ("users", "app", "table", "InnoDB", 25, 4096, ""),
                ],
            ),
            (
                "FROM information_schema.COLUMNS AS column_info",
                [
                    ("events", "id", "bigint", "NO", None, 1, "", "identifier", None),
                    ("users", "email", "varchar(255)", "NO", None, 1, "", "", "utf8mb4_bin"),
                ],
            ),
            (
                "FROM information_schema.TABLE_CONSTRAINTS AS constraint_info",
                [
                    ("events", "PRIMARY", "PRIMARY KEY", "id", 1),
                    ("users", "users_email_key", "UNIQUE", "email", 1),
                ],
            ),
            (
                "FROM information_schema.STATISTICS AS index_info",
                [
                    ("events", "PRIMARY", "BTREE", 0, "id", 1, None, "A", "", ""),
                    ("users", "users_email_key", "BTREE", 0, "email", 1, None, "A", "", ""),
                ],
            ),
        ]
    )
    monkeypatch.setattr(pymysql, "connect", lambda **_: full_connection)
    full = MySQLConnector(_spec(engine)).search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            detail=SearchDetail.FULL,
        ),
        _policy(engine),
    )

    full_objects = list(full.objects)
    assert full_objects[0].details["columns"][0]["name"] == "id"
    assert full_objects[0].details["keys"] == [
        {"name": "PRIMARY", "type": "PRIMARY KEY", "columns": ["id"]}
    ]
    assert full_objects[0].details["indexes"][0]["primary"] is True
    assert full_objects[1].details["columns"][0]["name"] == "email"
    assert len(full_connection.catalog_statements) == 4
    assert all(
        "events" not in statement and "users" not in statement
        for statement in full_connection.catalog_statements
    )
    expected_timeout = (
        ("SET SESSION MAX_EXECUTION_TIME = %s", (1_250,))
        if engine == "mysql"
        else ("SET SESSION max_statement_time = %s", (1.25,))
    )
    assert full_connection.executed[:2] == [
        expected_timeout,
        ("START TRANSACTION READ ONLY", None),
    ]
    assert full_connection.rolled_back is True
    assert full_connection.closed is True
    assert any(
        params is not None and "events" in params and "users" in params
        for _, params in full_connection.executed
    )


@pytest.mark.parametrize("engine", ["mysql", "mariadb"])
def test_mysql_family_column_and_index_details_are_layered(
    engine: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    column_rows = {
        SearchDetail.NAMES: [("id", "app", "column")],
        SearchDetail.SUMMARY: [("id", "app", "column", "events", "bigint", "NO")],
        SearchDetail.FULL: [
            ("id", "app", "column", "events", "bigint", "NO", None, 1, "", "identifier", None)
        ],
    }
    for detail in SearchDetail:
        connection = RecordingMySQLConnection(
            [("column_info.COLUMN_NAME REGEXP %s", column_rows[detail])]
        )
        monkeypatch.setattr(pymysql, "connect", lambda value=connection, **_: value)
        result = MySQLConnector(_spec(engine)).search_objects(
            SearchObjectsRequest(
                object_type=DatabaseObjectType.COLUMN,
                table="events",
                detail=detail,
            ),
            _policy(engine),
        )
        details = list(result.objects)[0].details
        if detail is SearchDetail.NAMES:
            assert details == {}
        else:
            assert details == {
                "table": "events",
                "type": "bigint",
                "nullable": False,
                **(
                    {
                        "default": None,
                        "ordinal_position": 1,
                        "extra": "",
                        "comment": "identifier",
                        "collation": None,
                    }
                    if detail is SearchDetail.FULL
                    else {}
                ),
            }

    index_rows = {
        SearchDetail.NAMES: [("PRIMARY", "app", "index")],
        SearchDetail.SUMMARY: [("PRIMARY", "app", "index", "events", "BTREE", 0)],
        SearchDetail.FULL: [("PRIMARY", "app", "index", "events", "BTREE", 0)],
    }
    for detail in SearchDetail:
        responses: list[tuple[str, list[tuple[Any, ...]]]] = [
            ("index_info.INDEX_NAME REGEXP %s", index_rows[detail])
        ]
        if detail is SearchDetail.FULL:
            responses.append(
                (
                    "index_detail.SEQ_IN_INDEX",
                    [("events", "PRIMARY", "id", 1, None, "A", "", "")],
                )
            )
        connection = RecordingMySQLConnection(responses)
        monkeypatch.setattr(pymysql, "connect", lambda value=connection, **_: value)
        result = MySQLConnector(_spec(engine)).search_objects(
            SearchObjectsRequest(
                object_type=DatabaseObjectType.INDEX,
                table="events",
                detail=detail,
            ),
            _policy(engine),
        )
        details = list(result.objects)[0].details
        if detail is SearchDetail.NAMES:
            assert details == {}
        else:
            assert details["table"] == "events"
            assert details["type"] == "BTREE"
            assert details["unique"] is True
            assert details["primary"] is True
            if detail is SearchDetail.SUMMARY:
                assert "columns" not in details
            else:
                assert details["columns"] == [
                    {
                        "name": "id",
                        "position": 1,
                        "prefix_length": None,
                        "order": "A",
                        "nullable": False,
                    }
                ]


class RecordingResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class RecordingPostgresConnection:
    def __init__(self, responses: list[tuple[str, list[tuple[Any, ...]]]]) -> None:
        self._responses = responses
        self.executed: list[tuple[str, Any]] = []

    @property
    def catalog_statements(self) -> list[str]:
        return [
            statement
            for statement, _ in self.executed
            if "SET TRANSACTION" not in statement and "set_config" not in statement
        ]

    def __enter__(self) -> RecordingPostgresConnection:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def transaction(self):
        return nullcontext()

    def execute(self, statement: Any, params: Any = None) -> RecordingResult:
        text = str(statement)
        self.executed.append((text, params))
        for marker, rows in self._responses:
            if marker in text:
                return RecordingResult(rows)
        return RecordingResult([])


class RecordingMySQLCursor:
    def __init__(self, connection: RecordingMySQLConnection) -> None:
        self._connection = connection
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> RecordingMySQLCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: Any = None) -> None:
        self._connection.executed.append((statement, params))
        self._rows = []
        for marker, rows in self._connection.responses:
            if marker in statement:
                self._rows = rows
                break

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class RecordingMySQLConnection:
    def __init__(self, responses: list[tuple[str, list[tuple[Any, ...]]]]) -> None:
        self.responses = responses
        self.executed: list[tuple[str, Any]] = []
        self.rolled_back = False
        self.closed = False

    @property
    def catalog_statements(self) -> list[str]:
        return [
            statement
            for statement, _ in self.executed
            if not statement.startswith("SET SESSION")
            and statement != "START TRANSACTION READ ONLY"
        ]

    def cursor(self) -> RecordingMySQLCursor:
        return RecordingMySQLCursor(self)

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True
