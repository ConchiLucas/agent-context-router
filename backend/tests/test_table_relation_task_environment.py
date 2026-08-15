from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from context_router.repositories.table_relation_repository import (
    InMemoryTableRelationRepository,
    TableJoinEvidenceRecord,
    TableJoinRelationRecord,
    TableRelationBuildRecord,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.table_relations import (
    TableRelationService,
    TableRelationServiceError,
)


class _TaskRepository:
    def __init__(self, tasks: dict[int, TaskRecord]) -> None:
        self._tasks = tasks

    def get_task(self, task_id: int) -> TaskRecord:
        return self._tasks[task_id]


class _Registry:
    def __init__(self) -> None:
        self.snapshot = SimpleNamespace(
            projects=[
                SimpleNamespace(
                    id="project-mtp",
                    name="c12-mtp",
                    project_kind="backend",
                )
            ]
        )

    def get_workspace_snapshot_for_task(self, **_: object) -> object:
        return self.snapshot

    def get_workspace_snapshot(self, _: str) -> object:
        return self.snapshot


@dataclass(frozen=True)
class _ResolvedDatabase:
    link_id: str
    project_id: str
    project_name: str
    mcp_alias: str
    database_remote_name: str
    database_display_name: str
    data_source_name: str = "panzhihua-mysql"
    engine: str = "mysql"
    readonly: bool = True
    database_available: bool = True
    database_system: bool = False


class _DataSourceRepository:
    def __init__(self) -> None:
        self.databases = [
            _ResolvedDatabase(
                link_id="link-test",
                project_id="project-mtp",
                project_name="c12-mtp",
                mcp_alias="c12_mtp_test_mtp",
                database_remote_name="test_mtp",
                database_display_name="TEST MTP",
            ),
            _ResolvedDatabase(
                link_id="link-uat",
                project_id="project-mtp",
                project_name="c12-mtp",
                mcp_alias="c12_mtp_uat_mtp",
                database_remote_name="uat_mtp",
                database_display_name="UAT MTP",
            ),
        ]

    def list_workspace_databases_for_mcp(self, _: str) -> list[_ResolvedDatabase]:
        return self.databases


def _task(task_id: int, environment: str) -> TaskRecord:
    return TaskRecord(
        id=task_id,
        project_id="project-mtp",
        project_key="mtp",
        project_name="c12-mtp",
        task="查询表关联",
        cwd="/workspace",
        agent_name="test",
        created_at=datetime.now(UTC),
        scope="workspace",
        workspace_id="workspace-1",
        workspace_key="workspace-key",
        workspace_name="workspace",
        database_environment=environment,
        database_environment_revision=8,
        database_environment_selection=(
            "workspace_default" if environment == "test" else "task_explicit"
        ),
    )


def _repository() -> InMemoryTableRelationRepository:
    repository = InMemoryTableRelationRepository()
    repository.replace_default_databases(
        workspace_id="workspace-1",
        expected_revision=0,
        targets=[("project-mtp", "link-uat")],
    )
    repository.mark_building(
        workspace_id="workspace-1",
        project_id="project-mtp",
        project_name="c12-mtp",
        database_key="c12_mtp_uat_mtp",
        generation_id="generation-uat",
        config_revision=1,
    )
    repository.publish(
        build=TableRelationBuildRecord(
            workspace_id="workspace-1",
            project_id="project-mtp",
            project_name="c12-mtp",
            database_key="c12_mtp_uat_mtp",
            generation_id="generation-uat",
            status="building",
            sql_file_count=1,
            statement_count=1,
            relation_count=1,
            warnings=(),
            error_message=None,
            started_at=datetime.now(UTC),
            finished_at=None,
            config_revision=1,
        ),
        relations=[
            TableJoinRelationRecord(
                relation_id="relation-uat",
                workspace_id="workspace-1",
                project_id="project-mtp",
                project_name="c12-mtp",
                database_key="c12_mtp_uat_mtp",
                table_a_schema="uat_mtp",
                table_a_name="carrier_order",
                table_b_schema="uat_mtp",
                table_b_name="dispatch_order",
                column_pairs=(("carrier_order_no", "carrier_order_no"),),
                evidences=(
                    TableJoinEvidenceRecord(
                        source_path="sql/uat.sql",
                        join_expression="c.carrier_order_no = d.carrier_order_no",
                        sql_statement="SELECT 1",
                    ),
                ),
            )
        ],
    )
    return repository


def _service(repository: InMemoryTableRelationRepository | None = None) -> TableRelationService:
    return TableRelationService(
        registry=_Registry(),  # type: ignore[arg-type]
        task_repository=_TaskRepository({1: _task(1, "test"), 2: _task(2, "uat")}),
        data_source_repository=_DataSourceRepository(),  # type: ignore[arg-type]
        repository=repository or _repository(),
        connector_manager=None,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize("task_id", [1, 2])
def test_table_relation_uses_workspace_default_independent_of_task_environment(
    task_id: int,
) -> None:
    result = _service().context_for_task(task_id=task_id, table="carrier_order")

    assert result.root_table.database_key == "c12_mtp_uat_mtp"
    assert [item.table_name for item in result.related_tables] == ["dispatch_order"]
    assert result.relation_database_scope.environment_independent is True
    assert result.relation_database_scope.source == "workspace_default"
    assert result.relation_database_scope.config_revision == 1


def test_default_database_configuration_lists_only_uat_as_selected() -> None:
    configuration = _service().get_default_database_configuration("workspace-1")

    assert configuration.configured is True
    assert configuration.configured_project_count == 1
    assert configuration.eligible_project_count == 1
    assert configuration.projects[0].selected_project_database_id == "link-uat"
    assert [item.selected for item in configuration.projects[0].options] == [False, True]


def test_replacing_default_database_makes_previous_generation_stale() -> None:
    repository = _repository()
    service = _service(repository)

    service.replace_default_databases(
        workspace_id="workspace-1",
        expected_revision=1,
        defaults=[("project-mtp", "link-test")],
    )

    assert service.get_status("workspace-1").status == "missing"
    with pytest.raises(TableRelationServiceError) as caught:
        service.context_for_task(task_id=2, table="carrier_order")
    assert caught.value.code == "table_relation_index_not_ready"


def test_default_database_update_requires_every_eligible_project() -> None:
    with pytest.raises(TableRelationServiceError) as caught:
        _service().replace_default_databases(
            workspace_id="workspace-1",
            expected_revision=1,
            defaults=[],
        )

    assert caught.value.code == "table_relation_default_database_incomplete"
