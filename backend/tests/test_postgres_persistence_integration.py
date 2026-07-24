from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.config import Config
from psycopg import sql
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

from alembic import command
from context_router.repositories.data_source_repository import PostgresDataSourceRepository
from context_router.repositories.database_call_repository import (
    DatabaseCallRepositoryError,
    DatabaseCallWrite,
    PostgresDatabaseCallRepository,
)
from context_router.repositories.mcp_tool_call_repository import PostgresMcpToolCallRepository

pytestmark = pytest.mark.postgresql

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REVISION_0007 = "20260722_0007"
_REVISION_0008 = "20260722_0008"
_REVISION_0009 = "20260724_0009"

_PROJECT_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_PROJECT_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_SOURCE_ID = "cccccccccccccccccccccccccccccccc"
_DATABASE_A = "dddddddddddddddddddddddddddddddd"
_DATABASE_B = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
_LINK_A = "11111111111111111111111111111111"
_LINK_B = "22222222222222222222222222222222"
_LINK_OTHER_PROJECT = "33333333333333333333333333333333"

_EXPECTED_ALIASES = {
    _LINK_A: "analytics_warehouse",
    _LINK_B: "analytics_warehouse_22222222",
    _LINK_OTHER_PROJECT: "analytics_warehouse",
}


@pytest.fixture
def isolated_postgres_database() -> Iterator[str]:
    configured_url = os.getenv("CONTEXT_ROUTER_DATABASE_URL", "").strip()
    if not configured_url:
        pytest.skip("CONTEXT_ROUTER_DATABASE_URL is not configured")

    try:
        configured = make_url(configured_url)
    except Exception:
        pytest.fail("CONTEXT_ROUTER_DATABASE_URL must be a valid PostgreSQL URL", pytrace=False)
    if not configured.drivername.startswith("postgresql"):
        pytest.skip("CONTEXT_ROUTER_DATABASE_URL does not target PostgreSQL")

    database_name = f"acr_persistence_it_{uuid4().hex}"
    admin_url = configured.set(drivername="postgresql").render_as_string(hide_password=False)
    temporary_url = configured.set(
        drivername="postgresql",
        database=database_name,
    ).render_as_string(hide_password=False)
    created = False

    try:
        try:
            with psycopg.connect(admin_url, autocommit=True) as connection:
                connection.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                )
            created = True
        except psycopg.errors.InsufficientPrivilege:
            pytest.skip("PostgreSQL role cannot CREATE DATABASE")
        except psycopg.Error as exc:
            pytest.fail(
                "temporary PostgreSQL database creation failed "
                f"(SQLSTATE {exc.sqlstate or 'unknown'})",
                pytrace=False,
            )

        yield temporary_url
    finally:
        if created:
            _drop_temporary_database(admin_url, database_name)


def test_migration_and_postgres_repositories_preserve_legacy_data(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    alembic_config = _alembic_config()

    command.upgrade(alembic_config, _REVISION_0007)
    assert _current_revision(database_url) == _REVISION_0007
    task_id = _insert_legacy_rows(database_url)

    command.upgrade(alembic_config, _REVISION_0008)
    assert _current_revision(database_url) == _REVISION_0008
    aliases = _aliases(database_url)
    assert aliases == _EXPECTED_ALIASES
    _assert_case_insensitive_unique_index(database_url, aliases[_LINK_A])
    legacy_read_id, legacy_database_call_id = _insert_legacy_call_rows(database_url, task_id)

    command.upgrade(alembic_config, _REVISION_0009)
    assert _current_revision(database_url) == _REVISION_0009
    tool_calls = PostgresMcpToolCallRepository(database_url).list_calls(task_id)
    assert [(call.tool_name, call.source) for call in tool_calls] == [
        ("read_context_document", "legacy"),
        ("execute_database_query", "legacy"),
    ]
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT tool_call_id FROM mcp_document_read_calls WHERE id = %s",
            (legacy_read_id,),
        ).fetchone() == (tool_calls[0].id,)
        assert connection.execute(
            "SELECT tool_call_id FROM mcp_database_calls WHERE id = %s",
            (legacy_database_call_id,),
        ).fetchone() == (tool_calls[1].id,)

    data_sources = PostgresDataSourceRepository(database_url)
    resolved = data_sources.get_project_database_by_alias(
        project_id=_PROJECT_A,
        mcp_alias="ANALYTICS_WAREHOUSE",
    )
    assert resolved.link_id == _LINK_A
    assert resolved.project_name == "Legacy Project A"
    assert resolved.database_id == _DATABASE_A
    assert resolved.database_remote_name == "warehouse_a"
    assert resolved.data_source_id == _SOURCE_ID
    assert resolved.data_source_category == "本机电脑"
    assert resolved.connection_config == {
        "host": "legacy-db.internal",
        "password": "legacy-secret",
        "username": "legacy-reader",
    }
    assert resolved.allowed_schemas == ["public"]
    assert resolved.max_rows == 321
    assert resolved.max_result_bytes == 654_321
    assert resolved.query_timeout_ms == 7_654

    same_alias_other_project = data_sources.get_project_database_by_alias(
        project_id=_PROJECT_B,
        mcp_alias="analytics_warehouse",
    )
    assert same_alias_other_project.link_id == _LINK_OTHER_PROJECT

    original_links = data_sources.list_links(project_id=_PROJECT_A)
    original_by_id = {link.id: link for link in original_links}
    swapped = data_sources.replace_project_links(
        _PROJECT_A,
        [
            replace(
                original_by_id[_LINK_A],
                mcp_alias=original_by_id[_LINK_B].mcp_alias,
            ),
            replace(
                original_by_id[_LINK_B],
                mcp_alias=original_by_id[_LINK_A].mcp_alias,
            ),
        ],
    )
    assert {link.id: link.mcp_alias for link in swapped} == {
        _LINK_A: aliases[_LINK_B],
        _LINK_B: aliases[_LINK_A],
    }
    assert (
        data_sources.get_project_database_by_alias(
            project_id=_PROJECT_A,
            mcp_alias="analytics_warehouse",
        ).link_id
        == _LINK_B
    )
    restored = data_sources.replace_project_links(_PROJECT_A, original_links)
    assert {link.id: link.mcp_alias for link in restored} == {
        _LINK_A: aliases[_LINK_A],
        _LINK_B: aliases[_LINK_B],
    }

    calls = PostgresDatabaseCallRepository(database_url)
    sql_digest = hashlib.sha256(b"SELECT id FROM public.events").hexdigest()
    call_id = calls.create_call(
        DatabaseCallWrite(
            task_id=task_id,
            operation="execute_query",
            database_alias=resolved.mcp_alias,
            engine="postgresql",
            status="ok",
            statement_type="select",
            sql_sha256=sql_digest,
            duration_ms=12,
            returned_count=2,
            result_bytes=48,
            truncated=False,
        )
    )
    recorded = calls.list_calls(task_id)
    assert [item.id for item in recorded] == [legacy_database_call_id, call_id]
    assert recorded[-1].sql_sha256 == sql_digest
    assert recorded[-1].returned_count == 2
    assert _database_call_columns(database_url).isdisjoint({"sql", "rows", "result"})

    with pytest.raises(DatabaseCallRepositoryError, match="任务不存在"):
        calls.create_call(
            DatabaseCallWrite(
                task_id=task_id + 1_000_000,
                operation="search_objects",
                database_alias="analytics_warehouse",
                engine="postgresql",
                status="error",
                error_code="database_not_found",
            )
        )

    with psycopg.connect(database_url) as connection:
        connection.execute("DELETE FROM mcp_tasks WHERE id = %s", (task_id,))
    assert calls.list_calls(task_id) == []

    command.downgrade(alembic_config, _REVISION_0007)
    assert _current_revision(database_url) == _REVISION_0007
    _assert_legacy_rows_survive(database_url)
    with psycopg.connect(database_url) as connection:
        assert connection.execute("SELECT to_regclass('public.mcp_database_calls')").fetchone() == (
            None,
        )

    command.upgrade(alembic_config, "head")
    assert _current_revision(database_url) == _REVISION_0009
    assert _aliases(database_url) == aliases
    _assert_legacy_rows_survive(database_url)


def _alembic_config() -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    return config


def _insert_legacy_rows(database_url: str) -> int:
    created_first = datetime(2026, 1, 1, tzinfo=UTC)
    created_second = datetime(2026, 1, 2, tzinfo=UTC)
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO document_projects
            (id, name, agents_path, enabled, project_type, created_at, updated_at)
            VALUES (%s, %s, %s, true, %s, %s, %s),
                   (%s, %s, %s, true, %s, %s, %s)""",
            (
                _PROJECT_A,
                "Legacy Project A",
                "/legacy/project-a/AGENTS.md",
                "公司项目",
                created_first,
                created_first,
                _PROJECT_B,
                "Legacy Project B",
                "/legacy/project-b/AGENTS.md",
                "公司项目",
                created_first,
                created_first,
            ),
        )
        connection.execute(
            """INSERT INTO data_sources
            (id, name, category, engine, description, connection_config, enabled,
             config_version, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, true, %s, %s, %s)""",
            (
                _SOURCE_ID,
                "Legacy PostgreSQL",
                "本机电脑",
                "postgresql",
                "legacy source",
                Jsonb(
                    {
                        "host": "legacy-db.internal",
                        "username": "legacy-reader",
                        "password": "legacy-secret",
                    }
                ),
                7,
                created_first,
                created_first,
            ),
        )
        connection.execute(
            """INSERT INTO data_source_databases
            (id, data_source_id, remote_name, display_name, namespace_type, available,
             system_database, metadata, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 'database', true, false, %s, %s, %s),
                   (%s, %s, %s, %s, 'database', true, false, %s, %s, %s)""",
            (
                _DATABASE_A,
                _SOURCE_ID,
                "warehouse_a",
                "Warehouse A",
                Jsonb({"owner": "legacy"}),
                created_first,
                created_first,
                _DATABASE_B,
                _SOURCE_ID,
                "warehouse_b",
                "Warehouse B",
                Jsonb({"owner": "legacy"}),
                created_first,
                created_first,
            ),
        )
        connection.execute(
            """INSERT INTO project_databases
            (id, project_id, database_id, alias, purpose, enabled, readonly,
             allowed_schemas, max_rows, max_result_bytes, query_timeout_ms,
             created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, true, true, %s, %s, %s, %s, %s, %s),
                   (%s, %s, %s, %s, %s, true, true, %s, %s, %s, %s, %s, %s),
                   (%s, %s, %s, %s, %s, true, true, %s, %s, %s, %s, %s, %s)""",
            (
                _LINK_A,
                _PROJECT_A,
                _DATABASE_A,
                "Analytics Warehouse",
                "legacy analytics",
                Jsonb(["public"]),
                321,
                654_321,
                7_654,
                created_first,
                created_first,
                _LINK_B,
                _PROJECT_A,
                _DATABASE_B,
                "analytics warehouse",
                "legacy archive",
                Jsonb(["archive"]),
                100,
                200_000,
                5_000,
                created_second,
                created_second,
                _LINK_OTHER_PROJECT,
                _PROJECT_B,
                _DATABASE_A,
                "ANALYTICS WAREHOUSE",
                "other project analytics",
                Jsonb(["public"]),
                100,
                200_000,
                5_000,
                created_first,
                created_first,
            ),
        )
        row = connection.execute(
            """INSERT INTO mcp_tasks
            (project_key, project_name, task, cwd, agent_name)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id""",
            (
                _PROJECT_A,
                "Legacy Project A",
                "verify PostgreSQL persistence",
                "/legacy/project-a",
                "pytest",
            ),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _assert_case_insensitive_unique_index(database_url: str, alias: str) -> None:
    with psycopg.connect(database_url) as connection:
        index_row = connection.execute(
            """SELECT indexdef FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'project_databases'
              AND indexname = 'uq_project_databases_project_mcp_alias'"""
        ).fetchone()
    assert index_row is not None
    index_definition = str(index_row[0]).lower()
    assert "unique index" in index_definition
    assert "lower" in index_definition

    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "UPDATE project_databases SET mcp_alias = %s WHERE id = %s",
                (alias, _LINK_B),
            )


def _insert_legacy_call_rows(database_url: str, task_id: int) -> tuple[int, int]:
    created_read = datetime(2026, 1, 3, tzinfo=UTC)
    created_database = datetime(2026, 1, 4, tzinfo=UTC)
    with psycopg.connect(database_url) as connection:
        read_row = connection.execute(
            """
            INSERT INTO mcp_document_read_calls (task_id, created_at)
            VALUES (%s, %s)
            RETURNING id
            """,
            (task_id, created_read),
        ).fetchone()
        assert read_row is not None
        read_call_id = int(read_row[0])
        connection.execute(
            """
            INSERT INTO mcp_document_read_items (
                read_call_id,
                position,
                document_id,
                document_path,
                status
            )
            VALUES (%s, 1, 'legacy-doc', 'docs/legacy.md', 'ok')
            """,
            (read_call_id,),
        )
        database_row = connection.execute(
            """
            INSERT INTO mcp_database_calls (
                task_id,
                operation,
                database_alias,
                engine,
                statement_type,
                status,
                duration_ms,
                returned_count,
                result_bytes,
                truncated,
                created_at
            )
            VALUES (
                %s,
                'execute_query',
                'analytics_warehouse',
                'postgresql',
                'select',
                'ok',
                9,
                1,
                24,
                false,
                %s
            )
            RETURNING id
            """,
            (task_id, created_database),
        ).fetchone()
    assert database_row is not None
    return read_call_id, int(database_row[0])


def _aliases(database_url: str) -> dict[str, str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            "SELECT id, mcp_alias FROM project_databases ORDER BY id"
        ).fetchall()
    return {str(row[0]): str(row[1]) for row in rows}


def _database_call_columns(database_url: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """SELECT column_name FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'mcp_database_calls'"""
        ).fetchall()
    return {str(row[0]) for row in rows}


def _assert_legacy_rows_survive(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        source_row = connection.execute(
            "SELECT id, connection_config, config_version FROM data_sources WHERE id = %s",
            (_SOURCE_ID,),
        ).fetchone()
        link_row = connection.execute(
            """SELECT id, database_id, allowed_schemas, max_rows,
                      max_result_bytes, query_timeout_ms
            FROM project_databases WHERE id = %s""",
            (_LINK_A,),
        ).fetchone()
    assert source_row == (
        _SOURCE_ID,
        {
            "host": "legacy-db.internal",
            "username": "legacy-reader",
            "password": "legacy-secret",
        },
        7,
    )
    assert link_row == (
        _LINK_A,
        _DATABASE_A,
        ["public"],
        321,
        654_321,
        7_654,
    )


def _current_revision(database_url: str) -> str:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT version_num FROM agent_context_router_alembic_version"
        ).fetchone()
    assert row is not None
    return str(row[0])


def _drop_temporary_database(admin_url: str, database_name: str) -> None:
    try:
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                """SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()""",
                (database_name,),
            )
            connection.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
            )
    except psycopg.Error as exc:
        raise AssertionError(
            f"temporary PostgreSQL database cleanup failed (SQLSTATE {exc.sqlstate or 'unknown'})"
        ) from None
