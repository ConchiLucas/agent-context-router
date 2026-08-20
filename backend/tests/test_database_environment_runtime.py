from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from context_router.config import Settings
from context_router.database.errors import DatabaseAccessError
from context_router.database.models import ConnectorCapabilities
from context_router.database.registry import ConnectorRegistry
from context_router.repositories.data_source_repository import ResolvedProjectDatabase
from context_router.repositories.database_environment_repository import (
    DatabaseEnvironmentConfigRecord,
    DatabaseEnvironmentMappingWrite,
    DatabaseEnvironmentRepositoryError,
    EnvironmentConfigurationSnapshot,
    EnvironmentPayloadsRecord,
    InMemoryDatabaseEnvironmentRepository,
    ResolvedEnvironmentMappingTarget,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.database_access import DatabaseAccessService


def _mapping() -> DatabaseEnvironmentMappingWrite:
    return DatabaseEnvironmentMappingWrite(
        id="mapping-1",
        workspace_id="workspace-1",
        project_id="project-1",
        logical_name="admin",
        mcp_alias="c12_admin_db",
        test_link_id="link-test",
        uat_link_id="link-uat",
    )


def test_in_memory_environment_mapping_defaults_to_local_and_switches_atomically() -> None:
    repository = InMemoryDatabaseEnvironmentRepository()

    saved = repository.replace_mappings(
        workspace_id="workspace-1",
        expected_revision=0,
        mappings=[_mapping()],
    )

    assert saved.active_environment == "local"
    assert saved.revision == 1
    assert (
        repository.resolve_mapping(
            workspace_id="workspace-1",
            environment="uat",
            mcp_alias="C12_ADMIN_DB",
        ).link_id
        == "link-uat"
    )

    switched = repository.switch_environment(
        workspace_id="workspace-1",
        environment="test",
        expected_revision=1,
    )

    assert switched.active_environment == "test"
    assert switched.revision == 2
    with pytest.raises(
        DatabaseEnvironmentRepositoryError,
        match="已被其他操作更新",
    ):
        repository.switch_environment(
            workspace_id="workspace-1",
            environment="uat",
            expected_revision=1,
        )


def test_environment_mapping_requires_at_least_one_mapping() -> None:
    repository = InMemoryDatabaseEnvironmentRepository()

    with pytest.raises(
        DatabaseEnvironmentRepositoryError,
        match="至少需要一条",
    ):
        repository.replace_mappings(
            workspace_id="workspace-1",
            expected_revision=0,
            mappings=[],
        )


def test_environment_json_can_switch_without_database_mappings() -> None:
    repository = InMemoryDatabaseEnvironmentRepository()

    saved = repository.replace_environment_payloads(
        workspace_id="workspace-1",
        expected_revision=0,
        environments={
            "test": {"mq": {"namespace": "test"}},
            "uat": {"mq": {"namespace": "uat"}},
        },
    )

    assert saved.active_environment == "local"
    assert saved.revision == 1
    assert repository.list_mappings("workspace-1") == []

    switched = repository.switch_environment(
        workspace_id="workspace-1",
        environment="test",
        expected_revision=1,
    )

    assert switched.active_environment == "test"
    assert switched.revision == 2


def test_environment_json_uses_shared_revision_and_tracks_active_environment() -> None:
    repository = InMemoryDatabaseEnvironmentRepository()
    repository.replace_mappings(
        workspace_id="workspace-1",
        expected_revision=0,
        mappings=[_mapping()],
    )
    test_config = {
        "mq": {"servers": ["test-mq:9876"]},
        "es": {"url": "http://test-es:9200"},
    }
    uat_config = {
        "mq": {"servers": ["uat-mq:9876"]},
        "minio": {"endpoint": "http://uat-minio:9000"},
    }

    saved = repository.replace_environment_payloads(
        workspace_id="workspace-1",
        expected_revision=1,
        environments={"test": test_config, "uat": uat_config},
    )

    assert saved.revision == 2
    assert saved.active_environment == "local"
    payloads = repository.get_environment_payloads("workspace-1")
    assert payloads.environments == {"test": test_config, "uat": uat_config}
    assert payloads.environments["uat"] is not uat_config

    switched = repository.switch_environment(
        workspace_id="workspace-1",
        environment="test",
        expected_revision=2,
    )
    assert switched.revision == 3
    assert (
        repository.get_environment_payloads("workspace-1").environments[switched.active_environment]
        == test_config
    )

    with pytest.raises(
        DatabaseEnvironmentRepositoryError,
        match="已被其他操作更新",
    ):
        repository.replace_environment_payloads(
            workspace_id="workspace-1",
            expected_revision=2,
            environments={"test": {}, "uat": {}},
        )


class _TaskRepository:
    def __init__(
        self,
        *,
        revision: int,
        scope: str = "workspace",
        environments: dict[int, tuple[str, str | None]] | None = None,
    ) -> None:
        self.revision = revision
        self.scope = scope
        self.environments = environments or {41: ("uat", None)}

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id in self.environments
        database_environment, database_environment_selection = self.environments[task_id]
        return TaskRecord(
            id=task_id,
            project_id="project-1",
            project_key="workspace-key",
            project_name="c12-admin",
            task="检查数据库",
            cwd="/workspace",
            agent_name="codex",
            created_at=datetime.now(UTC),
            scope=self.scope,  # type: ignore[arg-type]
            workspace_id="workspace-1" if self.scope == "workspace" else None,
            workspace_key="workspace-key" if self.scope == "workspace" else None,
            workspace_name="攀枝花" if self.scope == "workspace" else None,
            database_environment=(database_environment if self.scope == "workspace" else None),
            database_environment_revision=(self.revision if self.scope == "workspace" else None),
            database_environment_selection=(
                database_environment_selection if self.scope == "workspace" else None
            ),  # type: ignore[arg-type]
        )


class _Registry:
    def get_workspace_snapshot_for_task(self, **_: object) -> object:
        return object()

    def get_snapshot_for_task(self, **_: object) -> object:
        return SimpleNamespace(id="project-1", workspace_id="workspace-1")


class _EnvironmentRepository:
    def __init__(
        self,
        *,
        revision: int,
        mappings_configured: bool = True,
        active_environment: str = "uat",
        selector_configured: bool = True,
        payloads_configured: bool = False,
    ) -> None:
        self.revision = revision
        self.mappings_configured = mappings_configured
        self.active_environment = active_environment
        self.selector_configured = selector_configured
        self.payloads_configured = payloads_configured

    def get_active_config(self, workspace_id: str) -> DatabaseEnvironmentConfigRecord:
        assert workspace_id == "workspace-1"
        return DatabaseEnvironmentConfigRecord(
            workspace_id=workspace_id,
            active_environment=self.active_environment,  # type: ignore[arg-type]
            revision=self.revision,
        )

    def list_mappings(self, workspace_id: str) -> list[DatabaseEnvironmentMappingWrite]:
        assert workspace_id == "workspace-1"
        return [_mapping()] if self.mappings_configured else []

    def get_environment_snapshot(
        self,
        workspace_id: str,
    ) -> EnvironmentConfigurationSnapshot:
        return EnvironmentConfigurationSnapshot(
            config=self.get_active_config(workspace_id),
            selector_configured=self.selector_configured,
            payloads=EnvironmentPayloadsRecord(
                workspace_id=workspace_id,
                configured=self.payloads_configured,
                environments={
                    "test": {"name": "test"},
                    "uat": {"name": "uat"},
                },
            ),
        )

    def resolve_mapping(
        self,
        *,
        workspace_id: str,
        environment: str,
        mcp_alias: str,
    ) -> ResolvedEnvironmentMappingTarget:
        assert workspace_id == "workspace-1"
        assert environment in {"test", "uat"}
        assert mcp_alias == "c12_admin_db"
        return ResolvedEnvironmentMappingTarget(
            mapping_id="mapping-1",
            workspace_id=workspace_id,
            project_id="project-1",
            logical_name="admin",
            mcp_alias=mcp_alias,
            environment=environment,  # type: ignore[arg-type]
            link_id=f"link-{environment}",
        )

    def list_mapping_targets(
        self,
        *,
        workspace_id: str,
        environment: str,
    ) -> list[ResolvedEnvironmentMappingTarget]:
        return [
            self.resolve_mapping(
                workspace_id=workspace_id,
                environment=environment,
                mcp_alias="c12_admin_db",
            )
        ]


class _DataSourceRepository:
    def get_database_by_link_id(self, link_id: str) -> ResolvedProjectDatabase:
        assert link_id in {"link-test", "link-uat"}
        environment = link_id.removeprefix("link-")
        remote_name = f"{environment}_admin"
        now = datetime.now(UTC)
        return ResolvedProjectDatabase(
            link_id=link_id,
            workspace_id="workspace-1",
            project_id="project-1",
            project_name="c12-admin",
            project_kind="backend",
            mcp_alias=f"c12_admin_{remote_name}",
            alias=remote_name,
            purpose="项目数据源访问",
            readonly=True,
            allowed_schemas=[],
            max_rows=1000,
            max_result_bytes=2_000_000,
            query_timeout_ms=15_000,
            link_created_at=now,
            link_updated_at=now,
            database_id=f"database-{environment}",
            database_remote_name=remote_name,
            database_display_name=remote_name,
            namespace_type="database",
            database_available=True,
            database_system=False,
            database_metadata={},
            database_created_at=now,
            database_updated_at=now,
            data_source_id=f"source-{environment}",
            data_source_name=f"攀枝花 MySQL {environment.upper()}",
            data_source_category="公司内网服务器",
            engine="mysql",
            data_source_description="",
            connection_config={},
            config_version=1,
            source_created_at=now,
            source_updated_at=now,
        )

    def get_workspace_database_by_alias(
        self,
        *,
        workspace_id: str,
        mcp_alias: str,
    ) -> ResolvedProjectDatabase:
        assert workspace_id == "workspace-1"
        assert mcp_alias == "c12_admin_db"
        return self.get_database_by_link_id("link-uat")


def _access_service(
    *,
    task_revision: int,
    current_revision: int,
    task_scope: str = "workspace",
    mappings_configured: bool = True,
    task_environments: dict[int, tuple[str, str | None]] | None = None,
    active_environment: str = "uat",
    selector_configured: bool = True,
    payloads_configured: bool = False,
) -> DatabaseAccessService:
    connectors = ConnectorRegistry()
    connectors.register(
        "mysql",
        lambda _: None,
        ConnectorCapabilities(
            discover_databases=True,
            search_schemas=True,
            search_tables=True,
            search_views=True,
            search_columns=True,
            search_indexes=True,
            execute_readonly_query=True,
        ),
    )
    return DatabaseAccessService(
        settings=Settings(),
        registry=_Registry(),  # type: ignore[arg-type]
        task_repository=_TaskRepository(  # type: ignore[arg-type]
            revision=task_revision,
            scope=task_scope,
            environments=task_environments,
        ),
        data_source_repository=_DataSourceRepository(),  # type: ignore[arg-type]
        connector_registry=connectors,
        database_environment_repository=_EnvironmentRepository(  # type: ignore[arg-type]
            revision=current_revision,
            mappings_configured=mappings_configured,
            active_environment=active_environment,
            selector_configured=selector_configured,
            payloads_configured=payloads_configured,
        ),
    )


def test_environment_mapping_resolves_stable_alias_to_uat_physical_database() -> None:
    resolved = _access_service(task_revision=1, current_revision=1).resolve(
        task_id=41,
        mcp_alias="c12_admin_db",
    )

    assert resolved.database.mcp_alias == "c12_admin_db"
    assert resolved.database.database_remote_name == "uat_admin"
    assert resolved.database.link_id == "link-uat"


def test_environment_revision_change_rejects_stale_task_before_database_lookup() -> None:
    with pytest.raises(DatabaseAccessError) as captured:
        _access_service(task_revision=1, current_revision=2).resolve(
            task_id=41,
            mcp_alias="c12_admin_db",
        )

    assert captured.value.code == "environment_changed"


def test_legacy_project_task_is_rejected_after_workspace_environment_is_configured() -> None:
    with pytest.raises(DatabaseAccessError) as captured:
        _access_service(
            task_revision=1,
            current_revision=1,
            task_scope="project",
        ).resolve(
            task_id=41,
            mcp_alias="c12_admin_db",
        )

    assert captured.value.code == "environment_changed"


def test_json_only_environment_keeps_legacy_workspace_database_aliases() -> None:
    resolved = _access_service(
        task_revision=1,
        current_revision=1,
        mappings_configured=False,
    ).resolve(
        task_id=41,
        mcp_alias="c12_admin_db",
    )

    assert resolved.database.link_id == "link-uat"


def test_explicit_test_and_uat_tasks_route_without_switching_workspace_default() -> None:
    service = _access_service(
        task_revision=7,
        current_revision=7,
        task_environments={
            41: ("test", "task_explicit"),
            42: ("uat", "task_explicit"),
        },
        active_environment="test",
        payloads_configured=True,
    )

    test_database = service.resolve(
        task_id=41,
        mcp_alias="c12_admin_db",
    ).database
    uat_database = service.resolve(
        task_id=42,
        mcp_alias="c12_admin_db",
    ).database
    uat_prepared = service.list_prepared_workspace_databases(
        "workspace-1",
        database_environment="uat",
        database_environment_revision=7,
        database_environment_selection="task_explicit",
    )
    uat_payload = service.get_active_environment_payload(
        "workspace-1",
        environment="uat",
        revision=7,
        database_environment_selection="task_explicit",
    )

    assert test_database.link_id == "link-test"
    assert test_database.database_remote_name == "test_admin"
    assert uat_database.link_id == "link-uat"
    assert uat_database.database_remote_name == "uat_admin"
    assert [database.environment for database in uat_prepared] == ["uat"]
    assert uat_payload == {"name": "uat"}
    config = service.get_active_workspace_environment("workspace-1")
    assert config is not None
    assert config.active_environment == "test"


def test_workspace_default_task_still_requires_matching_active_environment() -> None:
    service = _access_service(
        task_revision=7,
        current_revision=7,
        task_environments={41: ("uat", "workspace_default")},
        active_environment="test",
    )

    with pytest.raises(DatabaseAccessError) as captured:
        service.resolve(
            task_id=41,
            mcp_alias="c12_admin_db",
        )

    assert captured.value.code == "environment_changed"


@pytest.mark.parametrize("task_id", [41, 42])
def test_shared_revision_change_invalidates_each_explicit_environment_task(
    task_id: int,
) -> None:
    service = _access_service(
        task_revision=7,
        current_revision=8,
        task_environments={
            41: ("test", "task_explicit"),
            42: ("uat", "task_explicit"),
        },
        active_environment="uat",
    )

    with pytest.raises(DatabaseAccessError) as captured:
        service.resolve(
            task_id=task_id,
            mcp_alias="c12_admin_db",
        )

    assert captured.value.code == "environment_changed"


def test_explicit_environment_task_fails_closed_when_selector_is_absent() -> None:
    service = _access_service(
        task_revision=7,
        current_revision=7,
        task_environments={41: ("uat", "task_explicit")},
        selector_configured=False,
    )

    with pytest.raises(DatabaseAccessError) as captured:
        service.resolve(
            task_id=41,
            mcp_alias="c12_admin_db",
        )

    assert captured.value.code == "environment_changed"
