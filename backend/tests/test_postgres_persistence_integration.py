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
from context_router.repositories.database_environment_repository import (
    PostgresDatabaseEnvironmentRepository,
)
from context_router.repositories.mcp_tool_call_repository import PostgresMcpToolCallRepository
from context_router.repositories.nacos_profile_repository import (
    NacosProfileWrite,
    PostgresNacosProfileRepository,
)
from context_router.repositories.project_repository import PostgresProjectRepository
from context_router.repositories.task_repository import PostgresTaskRepository
from context_router.repositories.workspace_repository import PostgresWorkspaceRepository

pytestmark = pytest.mark.postgresql

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_REVISION_0007 = "20260722_0007"
_REVISION_0008 = "20260722_0008"
_REVISION_0009 = "20260724_0009"
_REVISION_0010 = "20260724_0010"
_REVISION_0011 = "20260725_0011"
_REVISION_0012 = "20260725_0012"
_REVISION_0013 = "20260726_0013"
_REVISION_0014 = "20260726_0014"
_REVISION_0015 = "20260726_0015"
_REVISION_0016 = "20260727_0016"
_REVISION_0020 = "20260730_0020"
_REVISION_0022 = "20260730_0022"
_REVISION_0023 = "20260802_0023"
_REVISION_0024 = "20260808_0024"
_REVISION_HEAD = "20260824_0060"

_PROJECT_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_PROJECT_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_SOURCE_ID = "cccccccccccccccccccccccccccccccc"
_DATABASE_A = "dddddddddddddddddddddddddddddddd"
_DATABASE_B = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"
_LINK_A = "11111111111111111111111111111111"
_LINK_B = "22222222222222222222222222222222"
_LINK_OTHER_PROJECT = "33333333333333333333333333333333"
_PROJECT_A_PATH = "/legacy/project-a/AGENTS.md"
_PROJECT_A_KEY = hashlib.sha256(_PROJECT_A_PATH.encode()).hexdigest()

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

    command.upgrade(alembic_config, _REVISION_0010)
    assert _current_revision(database_url) == _REVISION_0010
    with psycopg.connect(database_url) as connection:
        assert connection.execute(
            "SELECT project_id FROM mcp_tasks WHERE id = %s",
            (task_id,),
        ).fetchone() == (_PROJECT_A,)

    calls = PostgresDatabaseCallRepository(database_url)
    sql_digest = hashlib.sha256(b"SELECT id FROM public.events").hexdigest()
    call_id = calls.create_call(
        DatabaseCallWrite(
            task_id=task_id,
            operation="execute_query",
            database_alias=aliases[_LINK_A],
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
    assert _current_revision(database_url) == _REVISION_HEAD
    assert _aliases(database_url) == aliases
    _assert_legacy_rows_survive(database_url)
    _assert_legacy_projects_migrated_to_workspaces(database_url)
    _assert_workspace_alias_unique_index(database_url, aliases[_LINK_A])
    _assert_business_enabled_columns_removed(database_url)

    nacos_profiles = PostgresNacosProfileRepository(database_url)
    saved_profile = nacos_profiles.upsert_profile(
        NacosProfileWrite(
            workspace_id=_PROJECT_A,
            profile_key="local",
            base_url="http://nacos.internal:8848",
            namespace_id="public",
            username="nacos",
            password="private",
            request_timeout_ms=5000,
            components=[
                {
                    "id": "redis-main",
                    "type": "redis",
                    "sources": [{"data_id": "application.yaml", "group": "DEFAULT_GROUP"}],
                    "fields": {
                        "password": {
                            "paths": ["spring.data.redis.password"],
                            "secret": True,
                        }
                    },
                }
            ],
        )
    )
    assert saved_profile.password == "private"
    assert nacos_profiles.get_profile(_PROJECT_A, "local") == saved_profile

    data_sources = PostgresDataSourceRepository(database_url)
    resolved = data_sources.get_workspace_database_by_alias(
        workspace_id=_PROJECT_A,
        mcp_alias="ANALYTICS_WAREHOUSE",
    )
    assert resolved.link_id == _LINK_A
    assert resolved.workspace_id == _PROJECT_A
    assert resolved.project_name == "Legacy Project A"
    assert resolved.project_kind == "backend"
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

    same_alias_other_workspace = data_sources.get_workspace_database_by_alias(
        workspace_id=_PROJECT_B,
        mcp_alias="analytics_warehouse",
    )
    assert same_alias_other_workspace.link_id == _LINK_OTHER_PROJECT

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
        data_sources.get_workspace_database_by_alias(
            workspace_id=_PROJECT_A,
            mcp_alias="analytics_warehouse",
        ).link_id
        == _LINK_B
    )
    restored = data_sources.replace_project_links(_PROJECT_A, original_links)
    assert {link.id: link.mcp_alias for link in restored} == {
        _LINK_A: aliases[_LINK_A],
        _LINK_B: aliases[_LINK_B],
    }
    _assert_task_project_snapshot_survives_project_deletion(database_url)


def test_trace_list_keeps_ordinary_tasks_without_internal_calls_and_excludes_system_tasks(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    task_ids: dict[str, int] = {}
    with psycopg.connect(database_url) as connection:
        for label, agent_name in (
            ("ordinary-no-call", "codex"),
            ("ordinary-external-only", "codex"),
            ("ordinary-read-without-prepare", "codex"),
            ("preview", "web-preview"),
            ("connection", "connection-test"),
        ):
            row = connection.execute(
                """
                INSERT INTO mcp_tasks (
                    project_key,
                    project_name,
                    task,
                    cwd,
                    agent_name
                )
                VALUES (%s, 'Trace Test', %s, '/trace-test', %s)
                RETURNING id
                """,
                ("trace-project-key", label, agent_name),
            ).fetchone()
            assert row is not None
            task_ids[label] = int(row[0])

        connection.execute(
            """
            INSERT INTO mcp_tool_calls (
                task_id,
                server_name,
                tool_name,
                source,
                status,
                finished_at
            )
            VALUES (%s, 'external-gateway', 'external_search', 'gateway', 'ok', CURRENT_TIMESTAMP)
            """,
            (task_ids["ordinary-external-only"],),
        )
        connection.execute(
            """
            INSERT INTO mcp_tool_calls (
                task_id,
                server_name,
                tool_name,
                source,
                status,
                finished_at
            )
            VALUES (
                %s,
                'context-router',
                'read_context_document',
                'server',
                'ok',
                CURRENT_TIMESTAMP
            )
            """,
            (task_ids["ordinary-read-without-prepare"],),
        )

    records = PostgresMcpToolCallRepository(database_url).list_traces(limit=100)
    records_by_task = {record.task: record for record in records}

    assert set(records_by_task) == {
        "ordinary-no-call",
        "ordinary-external-only",
        "ordinary-read-without-prepare",
    }
    assert records_by_task["ordinary-no-call"].call_count == 0
    assert records_by_task["ordinary-no-call"].prepare_call_count == 0
    assert records_by_task["ordinary-external-only"].call_count == 0
    assert records_by_task["ordinary-external-only"].server_names == []
    assert records_by_task["ordinary-read-without-prepare"].call_count == 1
    assert records_by_task["ordinary-read-without-prepare"].prepare_call_count == 0


def test_workspace_alias_migration_rejects_conflicts_without_renaming(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    alembic_config = _alembic_config()
    command.upgrade(alembic_config, _REVISION_0013)

    workspace_id = "56565656565656565656565656565656"
    project_a = "67676767676767676767676767676767"
    project_b = "78787878787878787878787878787878"
    source_id = "89898989898989898989898989898989"
    database_a = "90909090909090909090909090909090"
    database_b = "ababababababababababababababab01"
    link_a = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcd01"
    link_b = "efefefefefefefefefefefefefefef01"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO workspaces
                (id, name, workspace_type, root_path, enabled)
            VALUES (%s, '冲突工作空间', '公司项目', '/workspace/conflict', true)
            """,
            (workspace_id,),
        )
        connection.execute(
            """
            INSERT INTO document_projects (
                id, name, agents_path, enabled, project_type,
                workspace_id, relative_path
            )
            VALUES
                (%s, '前端', '/workspace/conflict/frontend/AGENTS.md', true,
                 '公司项目', %s, 'frontend'),
                (%s, '后端', '/workspace/conflict/backend/AGENTS.md', true,
                 '公司项目', %s, 'backend')
            """,
            (project_a, workspace_id, project_b, workspace_id),
        )
        connection.execute(
            """
            INSERT INTO data_sources (
                id, name, category, engine, description, connection_config,
                enabled, config_version
            )
            VALUES (%s, '冲突数据源', '本机电脑', 'postgresql', '', %s, true, 1)
            """,
            (source_id, Jsonb({})),
        )
        connection.execute(
            """
            INSERT INTO data_source_databases (
                id, data_source_id, remote_name, display_name,
                namespace_type, available, system_database, metadata
            )
            VALUES
                (%s, %s, 'frontend_db', '前端库', 'database', true, false, %s),
                (%s, %s, 'backend_db', '后端库', 'database', true, false, %s)
            """,
            (
                database_a,
                source_id,
                Jsonb({}),
                database_b,
                source_id,
                Jsonb({}),
            ),
        )
        connection.execute(
            """
            INSERT INTO project_databases (
                id, project_id, database_id, alias, mcp_alias, purpose,
                enabled, readonly, allowed_schemas
            )
            VALUES
                (%s, %s, %s, '前端库', 'shared_db', '', true, true, %s),
                (%s, %s, %s, '后端库', 'shared_db', '', true, true, %s)
            """,
            (
                link_a,
                project_a,
                database_a,
                Jsonb([]),
                link_b,
                project_b,
                database_b,
                Jsonb([]),
            ),
        )

    with pytest.raises(RuntimeError, match="工作空间内存在重复 MCP 数据库别名"):
        command.upgrade(alembic_config, _REVISION_0014)

    assert _current_revision(database_url) == _REVISION_0013
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT id, mcp_alias
            FROM project_databases
            WHERE id IN (%s, %s)
            ORDER BY id
            """,
            (link_a, link_b),
        ).fetchall()
        project_kind_column = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'document_projects'
              AND column_name = 'project_kind'
            """
        ).fetchone()
    assert rows == [(link_a, "shared_db"), (link_b, "shared_db")]
    assert project_kind_column is None


def test_postgres_workspace_and_project_repositories_keep_legacy_fields_in_sync(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")
    workspaces = PostgresWorkspaceRepository(database_url)
    projects = PostgresProjectRepository(database_url)
    workspace_id = "abababababababababababababababab"
    project_id = "cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd"

    workspaces.create_workspace(
        workspace_id=workspace_id,
        name="业务工作空间",
        workspace_type="业务系统",
        root_path="/workspace/company",
    )
    projects.create_project(
        project_id=project_id,
        workspace_id=workspace_id,
        relative_path="services/order",
        document_relative_path="docs/frontend/order/AGENTS.md",
        name="订单服务",
        project_kind="frontend",
    )
    created = projects.get_project(project_id)
    assert created.project_type == "业务系统"
    assert created.project_kind == "frontend"
    assert created.document_relative_path == "docs/frontend/order/AGENTS.md"
    assert created.agents_path == "/workspace/company/docs/frontend/order/AGENTS.md"
    assert created.workspace_name == "业务工作空间"

    workspaces.update_workspace(
        workspace_id,
        name="新工作空间",
        workspace_type="交通物流",
        root_path="/workspace/moved",
    )
    updated = projects.get_project(project_id)
    assert updated.project_type == "交通物流"
    assert updated.agents_path == "/workspace/moved/docs/frontend/order/AGENTS.md"
    assert updated.workspace_name == "新工作空间"

    projects.update_project(
        project_id,
        name="订单根项目",
        workspace_id=workspace_id,
        relative_path=".",
        document_relative_path="docs/backend/root/AGENTS.md",
        project_kind="backend",
    )
    moved = projects.get_project(project_id)
    assert moved.agents_path == "/workspace/moved/docs/backend/root/AGENTS.md"
    assert moved.project_kind == "backend"

    workspaces.delete_workspace(workspace_id)
    assert projects.list_projects(workspace_id) == []


def test_postgres_environment_json_can_switch_without_database_mappings(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")
    workspace_id = "56565656565656565656565656565657"
    PostgresWorkspaceRepository(database_url).create_workspace(
        workspace_id=workspace_id,
        name="JSON 环境工作空间",
        workspace_type="业务系统",
        root_path="/workspace/environment-json",
    )
    environments = {
        "test": {"rocketmq": {"namespace": "test"}},
        "uat": {"rocketmq": {"namespace": "uat"}},
    }
    repository = PostgresDatabaseEnvironmentRepository(database_url)

    saved = repository.replace_environment_payloads(
        workspace_id=workspace_id,
        expected_revision=0,
        environments=environments,
    )
    snapshot = repository.get_environment_snapshot(workspace_id)

    assert saved.active_environment == "local"
    assert snapshot.selector_configured is True
    assert snapshot.payloads.configured is True
    assert snapshot.payloads.environments == environments
    assert repository.list_mappings(workspace_id) == []

    switched = repository.switch_environment(
        workspace_id=workspace_id,
        environment="test",
        expected_revision=1,
    )

    assert switched.active_environment == "test"
    assert switched.revision == 2


def test_legacy_project_task_history_lists_document_and_database_activity(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    with psycopg.connect(database_url) as connection:
        task_ids: dict[str, int] = {}
        for task_name in ("prepare-only", "database-only", "document-read"):
            row = connection.execute(
                """
                INSERT INTO mcp_tasks (
                    project_id,
                    project_key,
                    project_name,
                    task,
                    cwd,
                    agent_name
                )
                VALUES (%s, %s, 'History Test', %s, '/history-test', 'codex')
                RETURNING id
                """,
                (_PROJECT_A, _PROJECT_A_KEY, task_name),
            ).fetchone()
            assert row is not None
            task_ids[task_name] = int(row[0])

        connection.execute(
            """
            INSERT INTO mcp_database_calls (
                task_id,
                operation,
                database_alias,
                engine,
                status
            )
            VALUES (%s, 'search_objects', 'analytics', 'postgresql', 'ok')
            """,
            (task_ids["database-only"],),
        )
        connection.execute(
            """
            INSERT INTO mcp_document_read_calls (task_id)
            VALUES (%s)
            """,
            (task_ids["document-read"],),
        )

    tasks = PostgresTaskRepository(database_url).list_tasks(
        _PROJECT_A_KEY,
        project_id=_PROJECT_A,
        limit=30,
    )

    assert [(task.task, task.read_call_count, task.scope) for task in tasks] == [
        ("document-read", 1, "project"),
        ("database-only", 0, "project"),
    ]


def test_workspace_task_repository_persists_scope_and_stable_snapshots(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    command.upgrade(_alembic_config(), "head")

    workspace_id = "12121212121212121212121212121212"
    project_id = "34343434343434343434343434343434"
    workspace_root = "/workspace/task-scope"
    workspace_key = hashlib.sha256(workspace_root.encode()).hexdigest()
    project_key = hashlib.sha256(f"{workspace_root}/frontend/AGENTS.md".encode()).hexdigest()
    workspaces = PostgresWorkspaceRepository(database_url)
    projects = PostgresProjectRepository(database_url)
    tasks = PostgresTaskRepository(database_url)

    workspaces.create_workspace(
        workspace_id=workspace_id,
        name="任务工作空间",
        workspace_type="业务系统",
        root_path=workspace_root,
    )
    projects.create_project(
        project_id=project_id,
        workspace_id=workspace_id,
        relative_path="frontend",
        name="前端项目",
        project_kind="frontend",
    )

    document_task_id = tasks.create_workspace_task(
        workspace_id=workspace_id,
        workspace_key=workspace_key,
        workspace_name="任务工作空间",
        active_project_id=project_id,
        active_project_name="前端项目",
        active_project_kind="frontend",
        task="读取前端文档",
        cwd=f"{workspace_root}/frontend",
        agent_name="codex",
    )
    database_task_id = tasks.create_workspace_task(
        workspace_id=workspace_id,
        workspace_key=workspace_key,
        workspace_name="任务工作空间",
        task="查询工作空间数据库",
        cwd=workspace_root,
        agent_name="codex",
        database_environment="test",
        database_environment_revision=4,
        database_environment_selection="task_explicit",
    )
    compatible_environment_task_id = tasks.create_workspace_task(
        workspace_id=workspace_id,
        workspace_key=workspace_key,
        workspace_name="任务工作空间",
        task="沿用工作空间环境",
        cwd=workspace_root,
        agent_name="codex",
        database_environment="uat",
        database_environment_revision=4,
    )
    legacy_task_id = tasks.create_task(
        project_id=project_id,
        project_key=project_key,
        project_name="前端项目",
        task="历史项目任务",
        cwd=f"{workspace_root}/frontend",
        agent_name="codex",
    )

    with psycopg.connect(database_url) as connection:
        connection.execute(
            "INSERT INTO mcp_document_read_calls (task_id) VALUES (%s)",
            (document_task_id,),
        )
        connection.execute(
            """
            INSERT INTO mcp_database_calls (
                task_id, operation, database_alias, engine, status
            )
            VALUES (%s, 'search_objects', 'workspace_db', 'postgresql', 'ok')
            """,
            (database_task_id,),
        )

    document_task = tasks.get_task(document_task_id)
    assert document_task.scope == "workspace"
    assert document_task.workspace_id == workspace_id
    assert document_task.workspace_key == workspace_key
    assert document_task.workspace_name == "任务工作空间"
    assert document_task.active_project_id == project_id
    assert document_task.active_project_name == "前端项目"
    assert document_task.active_project_kind == "frontend"

    database_task = tasks.get_task(database_task_id)
    assert database_task.scope == "workspace"
    assert database_task.active_project_id is None
    assert database_task.active_project_kind is None
    assert database_task.database_environment == "test"
    assert database_task.database_environment_revision == 4
    assert database_task.database_environment_selection == "task_explicit"
    compatible_environment_task = tasks.get_task(compatible_environment_task_id)
    assert compatible_environment_task.database_environment == "uat"
    assert compatible_environment_task.database_environment_selection == "workspace_default"
    assert tasks.get_task(legacy_task_id).scope == "project"

    workspace_history = tasks.list_workspace_tasks(
        workspace_id,
        workspace_key=workspace_key,
    )
    assert [
        (record.task, record.read_call_count, record.scope) for record in workspace_history
    ] == [
        ("查询工作空间数据库", 0, "workspace"),
        ("读取前端文档", 1, "workspace"),
    ]
    assert workspace_history[0].database_environment_selection == "task_explicit"

    workspaces.delete_workspace(workspace_id)
    retained = tasks.get_task(document_task_id)
    assert retained.workspace_id == workspace_id
    assert retained.active_project_id == project_id
    assert tasks.get_task(legacy_task_id).project_id == project_id


def test_task_environment_selection_migration_backfills_existing_environment_tasks(
    isolated_postgres_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = isolated_postgres_database
    monkeypatch.setenv("CONTEXT_ROUTER_DATABASE_URL", database_url)
    alembic_config = _alembic_config()
    command.upgrade(alembic_config, _REVISION_0020)

    workspace_id = "56565656565656565656565656565656"
    workspace_key = hashlib.sha256(b"/workspace/environment-selection").hexdigest()
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            INSERT INTO workspaces (
                id, name, workspace_type, root_path, enabled
            )
            VALUES (
                %s, 'Environment Selection', '公司项目',
                '/workspace/environment-selection', true
            )
            """,
            (workspace_id,),
        )
        rows = connection.execute(
            """
            INSERT INTO mcp_tasks (
                scope,
                workspace_id,
                workspace_key,
                workspace_name,
                project_key,
                project_name,
                task,
                cwd,
                agent_name,
                database_environment,
                database_environment_revision
            )
            VALUES
                (
                    'workspace', %s, %s, 'Environment Selection',
                    %s, 'Environment Selection', 'existing environment task',
                    '/workspace/environment-selection', 'pytest', 'uat', 3
                ),
                (
                    'workspace', %s, %s, 'Environment Selection',
                    %s, 'Environment Selection', 'existing environmentless task',
                    '/workspace/environment-selection', 'pytest', NULL, NULL
                ),
                (
                    'workspace', %s, %s, 'Environment Selection',
                    %s, 'Environment Selection', 'partial environment task',
                    '/workspace/environment-selection', 'pytest', 'test', NULL
                ),
                (
                    'workspace', %s, %s, 'Environment Selection',
                    %s, 'Environment Selection', 'partial revision task',
                    '/workspace/environment-selection', 'pytest', NULL, 4
                )
            RETURNING id
            """,
            (
                workspace_id,
                workspace_key,
                workspace_key,
                workspace_id,
                workspace_key,
                workspace_key,
                workspace_id,
                workspace_key,
                workspace_key,
                workspace_id,
                workspace_key,
                workspace_key,
            ),
        ).fetchall()

    command.upgrade(alembic_config, "head")
    assert _current_revision(database_url) == _REVISION_HEAD
    tasks = PostgresTaskRepository(database_url)
    environment_task = tasks.get_task(int(rows[0][0]))
    environmentless_task = tasks.get_task(int(rows[1][0]))
    partial_environment_task = tasks.get_task(int(rows[2][0]))
    partial_revision_task = tasks.get_task(int(rows[3][0]))
    assert environment_task.database_environment_selection == "workspace_default"
    assert environmentless_task.database_environment is None
    assert environmentless_task.database_environment_revision is None
    assert environmentless_task.database_environment_selection is None
    assert partial_environment_task.database_environment is None
    assert partial_environment_task.database_environment_revision is None
    assert partial_environment_task.database_environment_selection is None
    assert partial_revision_task.database_environment is None
    assert partial_revision_task.database_environment_revision is None
    assert partial_revision_task.database_environment_selection is None

    with pytest.raises(psycopg.errors.CheckViolation):
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                INSERT INTO mcp_tasks (
                    scope,
                    workspace_id,
                    workspace_key,
                    workspace_name,
                    project_key,
                    project_name,
                    task,
                    cwd,
                    database_environment,
                    database_environment_revision,
                    database_environment_selection
                )
                VALUES (
                    'workspace', %s, %s, 'Environment Selection',
                    %s, 'Environment Selection', 'invalid selection',
                    '/workspace/environment-selection', 'test', 3, NULL
                )
                """,
                (workspace_id, workspace_key, workspace_key),
            )


def _alembic_config() -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "migrations"))
    return config


def _assert_task_project_snapshot_survives_project_deletion(database_url: str) -> None:
    project_id = "ffffffffffffffffffffffffffffffff"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO workspaces
            (id, name, workspace_type, root_path)
            VALUES (%s, 'Disposable Workspace', '公司项目', '/disposable')""",
            (project_id,),
        )
        connection.execute(
            """INSERT INTO document_projects
            (
                id, name, agents_path, project_type, project_kind,
                workspace_id, relative_path, document_relative_path
            )
            VALUES (
                %s, 'Disposable Project', '/disposable/AGENTS.md',
                '公司项目', 'backend', %s, '.', 'AGENTS.md'
            )""",
            (project_id, project_id),
        )
        task_row = connection.execute(
            """INSERT INTO mcp_tasks
            (project_id, project_key, project_name, task, cwd, agent_name)
            VALUES (%s, %s, 'Disposable Project', 'retain snapshot', '/disposable', 'pytest')
            RETURNING id""",
            (project_id, hashlib.sha256(b"/disposable/AGENTS.md").hexdigest()),
        ).fetchone()
        assert task_row is not None
        connection.execute("DELETE FROM document_projects WHERE id = %s", (project_id,))
        retained = connection.execute(
            "SELECT project_id FROM mcp_tasks WHERE id = %s",
            (int(task_row[0]),),
        ).fetchone()
    assert retained == (project_id,)


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
                _PROJECT_A_PATH,
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
                _PROJECT_A_KEY,
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


def _assert_workspace_alias_unique_index(database_url: str, alias: str) -> None:
    with psycopg.connect(database_url) as connection:
        index_row = connection.execute(
            """SELECT indexdef FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'project_databases'
              AND indexname = 'uq_project_databases_workspace_mcp_alias'"""
        ).fetchone()
    assert index_row is not None
    index_definition = str(index_row[0]).lower()
    assert "unique index" in index_definition
    assert "workspace_id" in index_definition
    assert "lower" in index_definition

    with pytest.raises(psycopg.errors.UniqueViolation):
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """
                UPDATE project_databases
                SET workspace_id = %s, mcp_alias = %s
                WHERE id = %s
                """,
                (_PROJECT_A, alias, _LINK_OTHER_PROJECT),
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


def _assert_legacy_projects_migrated_to_workspaces(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT
                p.id,
                p.workspace_id,
                p.relative_path,
                p.document_relative_path,
                p.agents_path,
                p.project_kind,
                w.id,
                w.name,
                w.workspace_type,
                w.root_path
            FROM document_projects AS p
            JOIN workspaces AS w ON w.id = p.workspace_id
            ORDER BY p.id
            """
        ).fetchall()
    assert rows == [
        (
            _PROJECT_A,
            _PROJECT_A,
            ".",
            "AGENTS.md",
            _PROJECT_A_PATH,
            "backend",
            _PROJECT_A,
            "Legacy Project A",
            "公司项目",
            "/legacy/project-a",
        ),
        (
            _PROJECT_B,
            _PROJECT_B,
            ".",
            "AGENTS.md",
            "/legacy/project-b/AGENTS.md",
            "backend",
            _PROJECT_B,
            "Legacy Project B",
            "公司项目",
            "/legacy/project-b",
        ),
    ]
    with psycopg.connect(database_url) as connection:
        enabled_column = connection.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'document_projects'
              AND column_name = 'enabled'
            """
        ).fetchone()
    assert enabled_column is None


def _current_revision(database_url: str) -> str:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            "SELECT version_num FROM agent_context_router_alembic_version"
        ).fetchone()
    assert row is not None
    return str(row[0])


def _assert_business_enabled_columns_removed(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND column_name = 'enabled'
              AND table_name = ANY(%s)
            """,
            (
                [
                    "workspaces",
                    "data_sources",
                    "project_databases",
                    "workspace_database_environment_configs",
                ],
            ),
        ).fetchall()
    assert rows == []


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
