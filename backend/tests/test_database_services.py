from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.database.errors import DatabaseAccessError, DatabaseConnectorError
from context_router.database.manager import ConnectorManager
from context_router.database.models import (
    Column,
    ConnectorCapabilities,
    DatabaseObject,
    QueryResult,
    SearchObjectsResult,
)
from context_router.database.policy import SqlSafetyPolicy
from context_router.database.registry import ConnectorRegistry
from context_router.database.result import DatabaseResultFormatter
from context_router.repositories.data_source_repository import (
    DataSourceDatabaseRecord,
    DataSourceRecord,
    InMemoryDataSourceRepository,
    ProjectDatabaseLinkRecord,
)
from context_router.repositories.database_call_repository import InMemoryDatabaseCallRepository
from context_router.repositories.task_repository import TaskRecord
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.database_access import DatabaseAccessService
from context_router.services.database_catalog import DatabaseCatalogService
from context_router.services.database_query import DatabaseQueryService
from context_router.services.project_registry import ProjectRegistry


class FakeTaskRepository:
    def __init__(self, project_key: str) -> None:
        self.project_key = project_key

    def create_task(self, **values: object) -> int:
        return 41

    def get_task(self, task_id: int) -> TaskRecord:
        if task_id != 41:
            raise AssertionError("unexpected task")
        return TaskRecord(
            id=task_id,
            project_key=self.project_key,
            project_name="Analytics",
            task="inspect analytics",
            cwd="/workspace/analytics",
            agent_name="codex",
            created_at=datetime.now(UTC),
        )


class FakeConnector:
    capabilities = ConnectorCapabilities(
        discover_databases=True,
        search_schemas=True,
        search_tables=True,
        search_views=True,
        search_columns=True,
        search_indexes=True,
        execute_readonly_query=True,
    )

    def __init__(self, spec) -> None:
        self.spec = spec
        self.engine = spec.engine
        self.ping_count = 0
        self.search_count = 0
        self.query_count = 0
        self.fail_search = False
        self.closed = False

    def ping(self) -> None:
        self.ping_count += 1

    def discover_databases(self):
        return []

    def search_objects(self, request, policy):
        self.search_count += 1
        if self.fail_search:
            raise DatabaseConnectorError(
                "catalog_query_failed",
                "driver details must not escape",
            )
        return SearchObjectsResult(
            objects=[
                DatabaseObject(
                    name="event_daily",
                    schema="analytics",
                    kind="table",
                    details={"estimated_rows": 100},
                )
            ],
            elapsed_ms=4,
        )

    def execute_query(self, sql, policy):
        self.query_count += 1
        return QueryResult(
            columns=(Column("id", "UInt64"),),
            rows=((1,), (2,), (3,)),
            elapsed_ms=6,
        )

    def close(self) -> None:
        self.closed = True


def build_services(tmp_path: Path):
    root = tmp_path / "analytics" / "AGENTS.md"
    root.parent.mkdir(parents=True)
    root.write_text("# Analytics", encoding="utf-8")
    settings = Settings(
        workspace_host_root=tmp_path,
        workspace_container_root=tmp_path,
        default_project_name=None,
        default_agents_path=None,
        database_max_rows=2,
        database_max_result_bytes=50_000,
    )
    project_registry = ProjectRegistry(settings)
    project = project_registry.add_project(name="Analytics", agents_path=str(root))
    snapshot = project_registry.get_snapshot(project.id)
    task_repository = FakeTaskRepository(snapshot.project_key)
    repository = InMemoryDataSourceRepository()
    now = datetime.now(UTC)
    repository.create_data_source(
        DataSourceRecord(
            id="source-1",
            name="ClickHouse",
            category="本机电脑",
            engine="clickhouse",
            description="",
            connection_config={"host": "clickhouse"},
            enabled=True,
            config_version=1,
            database_count=0,
            project_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    repository.create_database(
        DataSourceDatabaseRecord(
            id="database-1",
            data_source_id="source-1",
            remote_name="analytics",
            display_name="Analytics",
            namespace_type="database",
            available=True,
            system_database=False,
            metadata={},
            project_count=0,
            created_at=now,
            updated_at=now,
        )
    )
    repository.create_link(
        ProjectDatabaseLinkRecord(
            id="link-1",
            project_id=project.id,
            project_name=project.name,
            database_id="database-1",
            database_name="analytics",
            data_source_id="source-1",
            data_source_name="ClickHouse",
            engine="clickhouse",
            alias="行为分析",
            mcp_alias="analytics",
            purpose="行为日志分析",
            enabled=True,
            readonly=True,
            allowed_schemas=[],
            max_rows=1000,
            max_result_bytes=2_000_000,
            query_timeout_ms=15_000,
            created_at=now,
            updated_at=now,
        )
    )
    connector_registry = ConnectorRegistry()
    created: list[FakeConnector] = []

    def factory(spec):
        connector = FakeConnector(spec)
        created.append(connector)
        return connector

    connector_registry.register("clickhouse", factory, FakeConnector.capabilities)
    manager = ConnectorManager(connector_registry)
    access = DatabaseAccessService(
        settings=settings,
        registry=project_registry,
        task_repository=task_repository,
        data_source_repository=repository,
        connector_registry=connector_registry,
    )
    calls = InMemoryDatabaseCallRepository()
    formatter = DatabaseResultFormatter()
    catalog = DatabaseCatalogService(
        settings=settings,
        access_service=access,
        connector_manager=manager,
        result_formatter=formatter,
        call_repository=calls,
    )
    query = DatabaseQueryService(
        access_service=access,
        connector_manager=manager,
        sql_policy=SqlSafetyPolicy(),
        result_formatter=formatter,
        call_repository=calls,
    )
    return (
        settings,
        project_registry,
        project,
        task_repository,
        access,
        catalog,
        query,
        calls,
        created,
        manager,
    )


def test_prepare_lists_database_without_opening_remote_connection(tmp_path: Path) -> None:
    (
        _,
        registry,
        project,
        tasks,
        access,
        _,
        _,
        _,
        created,
        manager,
    ) = build_services(tmp_path)
    service = ContextPreparationService(registry, tasks, access)

    result = service.prepare_for_project(project.id)

    assert result.databases[0].database == "analytics"
    assert result.databases[0].capabilities == ["search_objects", "execute_query"]
    assert created == []
    assert manager.cached_connector_count == 0


def test_search_and_query_are_project_scoped_bounded_and_recorded(tmp_path: Path) -> None:
    *_, catalog, query, calls, created, manager = build_services(tmp_path)[0:10]

    search_result = catalog.search(
        task_id=41,
        database="analytics",
        object_type="table",
    )
    query_result = query.execute(
        task_id=41,
        database="analytics",
        sql="SELECT id FROM events ORDER BY id",
    )

    assert search_result["objects"][0]["name"] == "event_daily"
    assert query_result["rows"] == [[1], [2]]
    assert query_result["returned_rows"] == 2
    assert query_result["truncated"] is True
    assert len(created) == 1
    assert created[0].ping_count == 1
    assert created[0].search_count == 1
    assert created[0].query_count == 1
    records = calls.list_calls(41)
    assert [record.operation for record in records] == ["search_objects", "execute_query"]
    assert records[1].sql_sha256 is not None
    assert manager.cached_connector_count == 1


def test_write_sql_is_rejected_before_a_connector_is_created(tmp_path: Path) -> None:
    values = build_services(tmp_path)
    query = values[6]
    calls = values[7]
    created = values[8]

    with pytest.raises(DatabaseAccessError) as captured:
        query.execute(
            task_id=41,
            database="analytics",
            sql="DROP TABLE events",
        )

    assert captured.value.code == "query_rejected"
    assert created == []
    assert calls.list_calls(41)[0].error_code == "query_rejected"


def test_catalog_failure_records_resolved_engine_and_returns_stable_error(
    tmp_path: Path,
) -> None:
    values = build_services(tmp_path)
    catalog = values[5]
    calls = values[7]
    created = values[8]

    catalog.search(task_id=41, database="analytics", object_type="table")
    created[0].fail_search = True

    with pytest.raises(DatabaseAccessError) as captured:
        catalog.search(task_id=41, database="analytics", object_type="table")

    assert captured.value.code == "catalog_query_failed"
    failed = calls.list_calls(41)[1]
    assert failed.status == "error"
    assert failed.database_alias == "analytics"
    assert failed.engine == "clickhouse"
    assert failed.error_code == "catalog_query_failed"


def test_access_rejections_are_recorded_for_a_valid_task(tmp_path: Path) -> None:
    values = build_services(tmp_path)
    catalog = values[5]
    query = values[6]
    calls = values[7]

    with pytest.raises(DatabaseAccessError) as catalog_error:
        catalog.search(task_id=41, database="missing", object_type="table")
    with pytest.raises(DatabaseAccessError) as query_error:
        query.execute(task_id=41, database="missing", sql="SELECT 1")

    assert catalog_error.value.code == "database_not_found"
    assert query_error.value.code == "database_not_found"
    records = calls.list_calls(41)
    assert [record.operation for record in records] == ["search_objects", "execute_query"]
    assert [record.database_alias for record in records] == ["missing", "missing"]
    assert [record.engine for record in records] == ["unknown", "unknown"]
    assert [record.error_code for record in records] == [
        "database_not_found",
        "database_not_found",
    ]
    assert records[1].sql_sha256 is not None
