from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import clickhouse_connect
import pytest
from fastapi.testclient import TestClient
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CallToolResult

from context_router.config import Settings
from context_router.database.connectors.clickhouse import ClickHouseConnector
from context_router.database.errors import DatabaseConnectorError
from context_router.database.manager import ConnectorManager
from context_router.database.models import (
    ConnectorSpec,
    DatabaseObjectType,
    EffectiveQueryPolicy,
    SearchDetail,
    SearchObjectsRequest,
)
from context_router.database.policy import SqlSafetyPolicy
from context_router.database.registry import ConnectorRegistry
from context_router.database.result import DatabaseResultFormatter, compact_json_bytes
from context_router.main import create_app
from context_router.mcp_server import create_context_router_mcp
from context_router.repositories.data_source_repository import (
    DataSourceDatabaseRecord,
    DataSourceRecord,
    InMemoryDataSourceRepository,
    ProjectDatabaseLinkRecord,
)
from context_router.repositories.database_call_repository import InMemoryDatabaseCallRepository
from context_router.repositories.document_read_repository import DocumentReadItemWrite
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.task_repository import TaskRecord, TaskRepositoryError
from context_router.services.context_document_read import ContextDocumentReadService
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.database_access import DatabaseAccessService
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.project_registry import ProjectRegistry

pytestmark = pytest.mark.clickhouse

_HOST = "clickhouse-test"
_PORT = 8123
_ADMIN_USER = "context_router_admin"
_ADMIN_PASSWORD = "context_router_admin"
_READER_USER = "context_router_reader"
_READER_PASSWORD = "context_router_reader"
_DATABASE = "context_router_test"
_TABLE = "unicode_指标"
_VIEW = "sample_view"
_TABLE_REF = f"`{_DATABASE}`.`{_TABLE}`"
_VIEW_REF = f"`{_DATABASE}`.`{_VIEW}`"


class IntegrationTaskRepository:
    def __init__(self, project_key: str) -> None:
        self._project_key = project_key
        self._next_task_id = 42
        self._tasks = {
            41: TaskRecord(
                id=41,
                project_key=project_key,
                project_name="ClickHouse Integration",
                task="inspect the integration database",
                cwd="/workspace/clickhouse-integration",
                agent_name="codex",
                created_at=datetime.now(UTC),
            )
        }

    def create_task(
        self,
        *,
        project_key: str,
        project_name: str,
        task: str,
        cwd: str,
        agent_name: str | None,
    ) -> int:
        task_id = self._next_task_id
        self._next_task_id += 1
        self._tasks[task_id] = TaskRecord(
            id=task_id,
            project_key=project_key,
            project_name=project_name,
            task=task,
            cwd=cwd,
            agent_name=agent_name,
            created_at=datetime.now(UTC),
        )
        return task_id

    def get_task(self, task_id: int) -> TaskRecord:
        try:
            return self._tasks[task_id]
        except KeyError as exc:
            raise TaskRepositoryError("任务不存在") from exc


class IntegrationDocumentReadRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[int, list[DocumentReadItemWrite]]] = []

    def create_read_call(
        self,
        *,
        task_id: int,
        items: list[DocumentReadItemWrite],
    ) -> int:
        self.calls.append((task_id, list(items)))
        return len(self.calls)


@dataclass(slots=True)
class IntegrationServiceHarness:
    settings: Settings
    project_registry: ProjectRegistry
    project_id: str
    root: Path
    task_repository: IntegrationTaskRepository
    read_repository: IntegrationDocumentReadRepository
    data_sources: InMemoryDataSourceRepository
    call_repository: InMemoryDatabaseCallRepository
    connector_registry: ConnectorRegistry
    manager: ConnectorManager
    preparation: ContextPreparationService
    document_read: ContextDocumentReadService
    catalog: DatabaseCatalogService
    query: DatabaseQueryService


def _clickhouse_service_is_addressable() -> bool:
    try:
        socket.getaddrinfo(_HOST, _PORT)
    except socket.gaierror:
        return False
    return True


@pytest.fixture(scope="module")
def clickhouse_connector() -> Iterator[ClickHouseConnector]:
    if not _clickhouse_service_is_addressable():
        pytest.skip(
            "ClickHouse integration service is not running; start it with "
            "docker compose --profile integration up -d clickhouse-test"
        )

    try:
        admin = clickhouse_connect.get_client(
            host=_HOST,
            port=_PORT,
            username=_ADMIN_USER,
            password=_ADMIN_PASSWORD,
            database="default",
            connect_timeout=5,
            send_receive_timeout=10,
        )
    except Exception as exc:
        pytest.fail(f"ClickHouse integration service is addressable but unavailable: {exc}")

    try:
        admin.command(f"CREATE DATABASE IF NOT EXISTS {_DATABASE}")
        admin.command(f"DROP VIEW IF EXISTS {_VIEW_REF}")
        admin.command(f"DROP TABLE IF EXISTS {_TABLE_REF}")
        admin.command(
            f"""CREATE TABLE {_TABLE_REF}
                (
                    id UInt64,
                    label Nullable(String),
                    tags Array(String),
                    INDEX idx_label label TYPE bloom_filter GRANULARITY 1
                )
                ENGINE = MergeTree
                ORDER BY id"""
        )
        admin.command(
            f"INSERT INTO {_TABLE_REF} VALUES (1, 'alpha', ['one']), (2, 'beta', ['two', 'three'])"
        )
        admin.command(f"CREATE VIEW {_VIEW_REF} AS SELECT id, label FROM {_TABLE_REF}")
        admin.command(
            f"CREATE USER IF NOT EXISTS {_READER_USER} "
            f"IDENTIFIED WITH plaintext_password BY '{_READER_PASSWORD}'"
        )
        admin.command(
            f"ALTER USER {_READER_USER} IDENTIFIED WITH plaintext_password BY '{_READER_PASSWORD}'"
        )
        admin.command(f"GRANT SELECT ON {_DATABASE}.* TO {_READER_USER}")
        admin.command(f"GRANT SELECT ON system.* TO {_READER_USER}")

        connector = ClickHouseConnector(
            ConnectorSpec(
                data_source_id="clickhouse-integration",
                config_version=1,
                database_id="clickhouse-integration-db",
                database_updated_at=datetime.now(UTC),
                engine="clickhouse",
                remote_name=_DATABASE,
                connection_config={
                    "host": _HOST,
                    "port": _PORT,
                    "username": _READER_USER,
                    "password": _READER_PASSWORD,
                    "secure": False,
                    "verify": True,
                },
            )
        )
        yield connector
        connector.close()
    finally:
        try:
            admin.command(f"DROP USER IF EXISTS {_READER_USER}")
            admin.command(f"DROP VIEW IF EXISTS {_VIEW_REF}")
            admin.command(f"DROP TABLE IF EXISTS {_TABLE_REF}")
        finally:
            admin.close()


@pytest.fixture(scope="module")
def query_policy() -> EffectiveQueryPolicy:
    return EffectiveQueryPolicy(
        engine="clickhouse",
        current_database=_DATABASE,
        readonly=True,
        allowed_schemas=(_DATABASE,),
        max_rows=2,
        max_result_bytes=1_000_000,
        query_timeout_ms=5_000,
    )


def _build_service_harness(
    tmp_path: Path,
    *,
    source_host: str = _HOST,
    source_port: int = _PORT,
    max_rows: int = 2,
    max_result_bytes: int = 100_000,
) -> IntegrationServiceHarness:
    root = tmp_path / "project" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text(
        "# ClickHouse Integration\n\n## MCP 验收\n真实协议文档读取内容。\n",
        encoding="utf-8",
    )
    settings = Settings(
        workspace_host_root=tmp_path,
        workspace_container_root=tmp_path,
        default_project_name=None,
        default_agents_path=None,
        database_max_rows=max_rows,
        database_max_result_bytes=max_result_bytes,
    )
    project_registry = ProjectRegistry(settings)
    project = project_registry.add_project(
        name="ClickHouse Integration",
        agents_path=str(root),
    )
    snapshot = project_registry.get_snapshot(project.id)
    task_repository = IntegrationTaskRepository(snapshot.project_key)
    data_sources = InMemoryDataSourceRepository()
    now = datetime.now(UTC)
    data_sources.create_data_source(
        DataSourceRecord(
            id="clickhouse-integration",
            name="ClickHouse Integration",
            category="本机电脑",
            engine="clickhouse",
            description="Compose integration service",
            connection_config={
                "host": source_host,
                "port": source_port,
                "username": _READER_USER,
                "password": _READER_PASSWORD,
            },
            enabled=True,
            config_version=1,
            database_count=0,
            project_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    data_sources.create_database(
        DataSourceDatabaseRecord(
            id="clickhouse-integration-db",
            data_source_id="clickhouse-integration",
            remote_name=_DATABASE,
            display_name="ClickHouse Integration",
            namespace_type="database",
            available=True,
            system_database=False,
            metadata={},
            project_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    data_sources.create_link(
        ProjectDatabaseLinkRecord(
            id="clickhouse-integration-link",
            project_id=project.id,
            project_name=project.name,
            database_id="clickhouse-integration-db",
            database_name=_DATABASE,
            data_source_id="clickhouse-integration",
            data_source_name="ClickHouse Integration",
            engine="clickhouse",
            alias="测试分析库",
            mcp_alias="analytics",
            purpose="真实 ClickHouse 服务链路验收",
            enabled=True,
            readonly=True,
            allowed_schemas=[_DATABASE],
            max_rows=max_rows,
            max_result_bytes=max_result_bytes,
            query_timeout_ms=5_000,
            created_at=now,
            updated_at=now,
        )
    )
    connector_registry = ConnectorRegistry()
    connector_registry.register(
        "clickhouse",
        ClickHouseConnector,
        ClickHouseConnector.capabilities,
    )
    manager = ConnectorManager(connector_registry)
    access_service = DatabaseAccessService(
        settings=settings,
        registry=project_registry,
        task_repository=task_repository,
        data_source_repository=data_sources,
        connector_registry=connector_registry,
    )
    call_repository = InMemoryDatabaseCallRepository()
    read_repository = IntegrationDocumentReadRepository()
    formatter = DatabaseResultFormatter()
    catalog = DatabaseCatalogService(
        settings=settings,
        access_service=access_service,
        connector_manager=manager,
        result_formatter=formatter,
        call_repository=call_repository,
    )
    query = DatabaseQueryService(
        access_service=access_service,
        connector_manager=manager,
        sql_policy=SqlSafetyPolicy(),
        result_formatter=formatter,
        call_repository=call_repository,
    )
    preparation = ContextPreparationService(
        project_registry,
        task_repository,
        access_service,
    )
    document_read = ContextDocumentReadService(
        project_registry,
        task_repository,
        read_repository,
    )
    return IntegrationServiceHarness(
        settings=settings,
        project_registry=project_registry,
        project_id=project.id,
        root=root,
        task_repository=task_repository,
        read_repository=read_repository,
        data_sources=data_sources,
        call_repository=call_repository,
        connector_registry=connector_registry,
        manager=manager,
        preparation=preparation,
        document_read=document_read,
        catalog=catalog,
        query=query,
    )


def _tool_payload(result: CallToolResult) -> dict[str, Any]:
    assert result.isError is False
    if result.structuredContent is not None:
        return result.structuredContent
    for content in result.content:
        if getattr(content, "type", None) != "text":
            continue
        value = json.loads(content.text)
        if isinstance(value, dict):
            return value
    raise AssertionError("MCP tool returned no structured JSON payload")


def _execute_query_through_fastmcp(
    harness: IntegrationServiceHarness,
    *,
    sql: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    server = create_context_router_mcp(
        harness.preparation,
        harness.document_read,
        harness.catalog,
        harness.query,
    )

    async def exercise_protocol() -> tuple[dict[str, Any], dict[str, Any]]:
        async with create_connected_server_and_client_session(
            server,
            read_timeout_seconds=timedelta(seconds=10),
            raise_exceptions=True,
        ) as session:
            prepared = _tool_payload(
                await session.call_tool(
                    "prepare_task_context",
                    arguments={
                        "task": "验证 ClickHouse 查询结果",
                        "cwd": str(harness.root.parent),
                        "agent_name": "codex-integration",
                    },
                )
            )
            queried = _tool_payload(
                await session.call_tool(
                    "execute_database_query",
                    arguments={
                        "task_id": prepared["task_id"],
                        "database": "analytics",
                        "sql": sql,
                    },
                )
            )
            return prepared, queried

    return asyncio.run(exercise_protocol())


def test_ping_and_discover_databases(clickhouse_connector: ClickHouseConnector) -> None:
    clickhouse_connector.ping()

    databases = clickhouse_connector.discover_databases()

    assert any(database.name == _DATABASE for database in databases)
    assert any(database.name == "system" and database.system_database for database in databases)


def test_search_objects_with_unicode_and_progressive_details(
    clickhouse_connector: ClickHouseConnector,
    query_policy: EffectiveQueryPolicy,
) -> None:
    tables = clickhouse_connector.search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.TABLE,
            glob="unicode_*",
            detail=SearchDetail.FULL,
            limit=10,
        ),
        query_policy,
    )
    views = clickhouse_connector.search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.VIEW,
            glob="sample_*",
            detail=SearchDetail.SUMMARY,
            limit=10,
        ),
        query_policy,
    )
    columns = clickhouse_connector.search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.COLUMN,
            table=_TABLE,
            glob="la*",
            detail=SearchDetail.FULL,
            limit=10,
        ),
        query_policy,
    )
    indexes = clickhouse_connector.search_objects(
        SearchObjectsRequest(
            object_type=DatabaseObjectType.INDEX,
            table=_TABLE,
            glob="idx_*",
            detail=SearchDetail.FULL,
            limit=10,
        ),
        query_policy,
    )

    table = list(tables.objects)[0]
    assert table.name == _TABLE
    assert table.details["engine"] == "MergeTree"
    assert {column["name"] for column in table.details["columns"]} >= {"id", "label"}
    assert [view.name for view in views.objects] == ["sample_view"]
    assert [column.name for column in columns.objects] == ["label"]
    assert [index.name for index in indexes.objects] == ["idx_label"]


def test_select_and_remote_row_limit(
    clickhouse_connector: ClickHouseConnector,
    query_policy: EffectiveQueryPolicy,
) -> None:
    result = clickhouse_connector.execute_query(
        "SELECT number, toString(number) AS label FROM numbers(10) ORDER BY number",
        query_policy,
    )

    assert [column.name for column in result.columns] == ["number", "label"]
    assert result.truncated is True
    assert len(list(result.rows)) == query_policy.max_rows + 1


def test_readonly_user_rejects_write_even_without_application_sql_policy(
    clickhouse_connector: ClickHouseConnector,
    query_policy: EffectiveQueryPolicy,
) -> None:
    with pytest.raises(DatabaseConnectorError) as error:
        clickhouse_connector.execute_query(
            f"INSERT INTO {_TABLE_REF} VALUES (3, 'blocked', [])",
            query_policy,
        )

    assert error.value.code == "query_failed"


def test_server_query_timeout_maps_to_stable_error(
    clickhouse_connector: ClickHouseConnector,
    query_policy: EffectiveQueryPolicy,
) -> None:
    timeout_policy = replace(query_policy, query_timeout_ms=100)

    with pytest.raises(DatabaseConnectorError) as error:
        clickhouse_connector.execute_query(
            "SELECT sleepEachRow(0.05) FROM numbers(20)",
            timeout_policy,
        )

    assert error.value.code == "query_timeout"


def test_real_connector_through_catalog_and_query_services(
    clickhouse_connector: ClickHouseConnector,
    tmp_path: Path,
) -> None:
    assert clickhouse_connector.engine == "clickhouse"
    harness = _build_service_harness(tmp_path)

    try:
        search_result = harness.catalog.search(
            task_id=41,
            database="analytics",
            object_type="table",
            pattern="unicode_*",
            detail="summary",
        )
        query_result = harness.query.execute(
            task_id=41,
            database="analytics",
            sql=f"SELECT id, label FROM `{_TABLE}` ORDER BY id",
        )
    finally:
        harness.manager.close_all()

    assert search_result["objects"][0]["name"] == _TABLE
    assert query_result["rows"] == [[1, "alpha"], [2, "beta"]]
    assert query_result["returned_rows"] == 2
    assert [call.operation for call in harness.call_repository.list_calls(41)] == [
        "search_objects",
        "execute_query",
    ]


def test_real_clickhouse_through_fastmcp_client_session(
    clickhouse_connector: ClickHouseConnector,
    tmp_path: Path,
) -> None:
    assert clickhouse_connector.engine == "clickhouse"
    harness = _build_service_harness(tmp_path)
    server = create_context_router_mcp(
        harness.preparation,
        harness.document_read,
        harness.catalog,
        harness.query,
    )

    async def exercise_protocol() -> tuple[
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        async with create_connected_server_and_client_session(
            server,
            read_timeout_seconds=timedelta(seconds=10),
            raise_exceptions=True,
        ) as session:
            tools = await session.list_tools()
            assert [tool.name for tool in tools.tools] == [
                "prepare_task_context",
                "read_context_document",
                "search_database_objects",
                "execute_database_query",
            ]

            prepared = _tool_payload(
                await session.call_tool(
                    "prepare_task_context",
                    arguments={
                        "task": "验证真实 ClickHouse MCP 链路",
                        "cwd": str(harness.root.parent),
                        "agent_name": "codex-integration",
                    },
                )
            )
            task_id = prepared["task_id"]
            root_document_id = prepared["documents"]["document_id"]
            searched = _tool_payload(
                await session.call_tool(
                    "search_database_objects",
                    arguments={
                        "task_id": task_id,
                        "database": "analytics",
                        "object_type": "table",
                        "pattern": "unicode_*",
                        "detail": "summary",
                    },
                )
            )
            queried = _tool_payload(
                await session.call_tool(
                    "execute_database_query",
                    arguments={
                        "task_id": task_id,
                        "database": "analytics",
                        "sql": f"SELECT id, label FROM `{_TABLE}` ORDER BY id",
                    },
                )
            )
            read = _tool_payload(
                await session.call_tool(
                    "read_context_document",
                    arguments={
                        "task_id": task_id,
                        "requests": [{"document_id": root_document_id}],
                    },
                )
            )
            return prepared, searched, queried, read

    try:
        prepared, searched, queried, read = asyncio.run(exercise_protocol())
    finally:
        harness.manager.close_all()

    task_id = prepared["task_id"]
    assert prepared["databases"] == [
        {
            "database": "analytics",
            "engine": "clickhouse",
            "name": "ClickHouse Integration",
            "purpose": "真实 ClickHouse 服务链路验收",
            "readonly": True,
            "capabilities": ["search_objects", "execute_query"],
        }
    ]
    assert searched["objects"][0]["name"] == _TABLE
    assert queried["rows"] == [[1, "alpha"], [2, "beta"]]
    assert read["documents"][0]["content"].endswith("真实协议文档读取内容。\n")
    assert harness.read_repository.calls[0][0] == task_id
    assert [call.operation for call in harness.call_repository.list_calls(task_id)] == [
        "search_objects",
        "execute_query",
    ]
    serialized_payloads = json.dumps(
        [prepared, searched, queried, read],
        ensure_ascii=False,
    )
    assert _ADMIN_PASSWORD not in serialized_payloads
    assert _READER_PASSWORD not in serialized_payloads


def test_fastmcp_formats_real_clickhouse_complex_types_as_json(
    clickhouse_connector: ClickHouseConnector,
    tmp_path: Path,
) -> None:
    assert clickhouse_connector.engine == "clickhouse"
    harness = _build_service_harness(tmp_path)
    sql = """
        SELECT
            toDecimal128('123.4500', 4) AS decimal_value,
            toUUID('12345678-1234-5678-1234-567812345678') AS uuid_value,
            toDateTime('2026-07-23 12:34:56', 'UTC') AS datetime_value,
            [toUInt8(1), toUInt8(2), toUInt8(3)] AS array_value,
            tuple('alpha', toUInt64(7)) AS tuple_value,
            map('first', toUInt64(1), 'second', toUInt64(2)) AS map_value
    """

    try:
        _, queried = _execute_query_through_fastmcp(harness, sql=sql)
    finally:
        harness.manager.close_all()

    column_names = [column["name"] for column in queried["columns"]]
    row = dict(zip(column_names, queried["rows"][0], strict=True))
    assert row["decimal_value"] == "123.4500"
    assert row["uuid_value"] == "12345678-1234-5678-1234-567812345678"
    assert row["datetime_value"] in {
        "2026-07-23T12:34:56",
        "2026-07-23T12:34:56+00:00",
    }
    assert row["array_value"] == [1, 2, 3]
    assert row["tuple_value"] == ["alpha", 7]
    assert row["map_value"] == {"first": 1, "second": 2}
    assert json.loads(json.dumps(queried, ensure_ascii=False, allow_nan=False)) == queried


def test_fastmcp_truncates_real_clickhouse_result_by_utf8_byte_budget(
    clickhouse_connector: ClickHouseConnector,
    tmp_path: Path,
) -> None:
    assert clickhouse_connector.engine == "clickhouse"
    byte_budget = 1_024
    harness = _build_service_harness(
        tmp_path,
        max_rows=20,
        max_result_bytes=byte_budget,
    )
    sql = """
        SELECT
            arrayJoin(range(6)) AS sequence,
            repeat('中文🙂', 14) AS payload
        ORDER BY sequence
    """

    try:
        _, queried = _execute_query_through_fastmcp(harness, sql=sql)
    finally:
        harness.manager.close_all()

    assert queried["result_bytes"] == len(compact_json_bytes(queried))
    assert queried["result_bytes"] <= byte_budget
    assert queried["truncated"] is True
    assert queried["truncation_reason"] == "bytes"
    assert 0 < queried["returned_rows"] < 6


def test_unreachable_clickhouse_does_not_block_document_mcp_or_health(
    tmp_path: Path,
) -> None:
    harness = _build_service_harness(
        tmp_path,
        source_host="127.0.0.1",
        source_port=1,
    )
    server = create_context_router_mcp(
        harness.preparation,
        harness.document_read,
        harness.catalog,
        harness.query,
    )

    async def exercise_protocol() -> tuple[
        dict[str, Any],
        dict[str, Any],
        int,
        CallToolResult,
    ]:
        async with create_connected_server_and_client_session(
            server,
            read_timeout_seconds=timedelta(seconds=10),
            raise_exceptions=True,
        ) as session:
            prepared = _tool_payload(
                await session.call_tool(
                    "prepare_task_context",
                    arguments={
                        "task": "ClickHouse 离线时读取项目文档",
                        "cwd": str(harness.root.parent),
                        "agent_name": "codex-integration",
                    },
                )
            )
            read = _tool_payload(
                await session.call_tool(
                    "read_context_document",
                    arguments={
                        "task_id": prepared["task_id"],
                        "requests": [{"document_id": prepared["documents"]["document_id"]}],
                    },
                )
            )
            cached_after_document_calls = harness.manager.cached_connector_count
            failed_query = await session.call_tool(
                "execute_database_query",
                arguments={
                    "task_id": prepared["task_id"],
                    "database": "analytics",
                    "sql": "SELECT 1",
                },
            )
            return prepared, read, cached_after_document_calls, failed_query

    health_manager = ConnectorManager(harness.connector_registry)
    health_app = create_app(
        settings=harness.settings,
        task_repository=harness.task_repository,
        document_read_repository=harness.read_repository,
        project_repository=InMemoryProjectRepository(),
        data_source_repository=harness.data_sources,
        database_call_repository=harness.call_repository,
        connector_registry=harness.connector_registry,
        connector_manager=health_manager,
    )

    try:
        prepared, read, cached_after_document_calls, failed_query = asyncio.run(exercise_protocol())
        with TestClient(health_app) as client:
            health_response = client.get("/health")
    finally:
        harness.manager.close_all()
        health_manager.close_all()

    assert prepared["databases"][0]["database"] == "analytics"
    assert read["documents"][0]["content"].endswith("真实协议文档读取内容。\n")
    assert cached_after_document_calls == 0
    assert failed_query.isError is True
    assert "connection_failed" in " ".join(
        content.text for content in failed_query.content if getattr(content, "type", None) == "text"
    )
    assert harness.manager.cached_connector_count == 0
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
