from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from context_router.repositories.database_context_repository import (
    InMemoryDatabaseContextRepository,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.services.database_context import DatabaseContextError, DatabaseContextService


class _Tasks:
    def __init__(self) -> None:
        self.records = {
            task_id: TaskRecord(
                id=task_id,
                project_id=None,
                project_key="workspace",
                project_name="Workspace",
                task="查询 UAT 数据",
                cwd="/workspace",
                agent_name="codex",
                created_at=datetime.now(UTC),
                scope="workspace",
                workspace_id="workspace-1",
                workspace_key="workspace",
                workspace_name="Workspace",
                database_environment="uat",
                database_environment_revision=8,
                database_environment_selection="task_description",
            )
            for task_id in (1, 2)
        }

    def get_task(self, task_id: int) -> TaskRecord:
        return self.records[task_id]


class _Access:
    def resolve(self, *, task_id: int, mcp_alias: str, **_: object):
        assert task_id in {1, 2}
        return SimpleNamespace(
            database=SimpleNamespace(
                mcp_alias=mcp_alias,
                link_id="link-1",
                database_remote_name="c12_mtp_uat",
            )
        )


class _Mappings:
    def source_for_task(self, mapping_id: str, *, task_id: int) -> dict[str, object]:
        assert task_id == 1
        return {
            "mapping_id": mapping_id,
            "database_alias": "c12_mtp_db",
            "schema_name": "c12_mtp_db",
            "table_name": "cs_dsly_order_entrusted",
        }


def _service(tasks: _Tasks) -> DatabaseContextService:
    return DatabaseContextService(
        contexts=InMemoryDatabaseContextRepository(),
        tasks=tasks,  # type: ignore[arg-type]
        access=_Access(),  # type: ignore[arg-type]
        value_mappings=_Mappings(),  # type: ignore[arg-type]
    )


def test_mapping_resolves_task_bound_database_context() -> None:
    service = _service(_Tasks())

    resolved = service.resolve_target(
        task_id=1,
        mapping_id="mapping-1",
        table_name=None,
        business_hint=None,
    )

    assert resolved["status"] == "resolved"
    assert resolved["environment"] == "uat"
    context_id = str(resolved["database_context_id"])
    assert service.alias_for_context(task_id=1, database_context_id=context_id) == "c12_mtp_db"


def test_database_context_cannot_be_reused_by_another_task() -> None:
    service = _service(_Tasks())
    resolved = service.resolve_target(
        task_id=1,
        mapping_id="mapping-1",
        table_name=None,
        business_hint=None,
    )

    with pytest.raises(DatabaseContextError) as caught:
        service.alias_for_context(
            task_id=2,
            database_context_id=str(resolved["database_context_id"]),
        )

    assert caught.value.code == "database_context_task_mismatch"


def test_database_context_rejects_changed_task_environment_revision() -> None:
    tasks = _Tasks()
    service = _service(tasks)
    resolved = service.resolve_target(
        task_id=1,
        mapping_id="mapping-1",
        table_name=None,
        business_hint=None,
    )
    tasks.records[1] = replace(tasks.records[1], database_environment_revision=9)

    with pytest.raises(DatabaseContextError) as caught:
        service.alias_for_context(
            task_id=1,
            database_context_id=str(resolved["database_context_id"]),
        )

    assert caught.value.code == "database_context_stale"
