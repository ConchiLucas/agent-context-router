from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from context_router.repositories.ai_log_investigation_repository import (
    InMemoryAiLogInvestigationRepository,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.schemas.workspaces import WorkspaceContainerSummary
from context_router.services.ai_log_visualization import (
    AiLogVisualizationError,
    AiLogVisualizationService,
)
from context_router.services.workspace_containers import (
    ContainerLogRecord,
    ContainerLogSnapshot,
)


class _Tasks:
    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == 7
        return TaskRecord(
            id=7,
            project_id=None,
            project_key="workspace-1",
            project_name="示例工作空间",
            task="排查合同查询接口报错",
            cwd="/workspace",
            agent_name="codex",
            created_at=datetime.now(UTC),
            scope="workspace",
            workspace_id="workspace-1",
            workspace_key="workspace-1",
            workspace_name="示例工作空间",
            database_environment="uat",
        )


class _Projects:
    def list_projects(self, workspace_id: str):
        assert workspace_id == "workspace-1"
        return [SimpleNamespace(id="project-1", name="合同服务", project_kind="backend")]


class _Workspaces:
    def get_workspace(self, workspace_id: str):
        assert workspace_id == "workspace-1"
        return SimpleNamespace(name="示例工作空间")


class _Containers:
    def __init__(self, records: list[ContainerLogRecord]) -> None:
        self.records = records

    def list_containers(self, workspace_id: str, **_: object):
        assert workspace_id == "workspace-1"
        return [
            WorkspaceContainerSummary(
                id="a" * 64,
                name="contract-api",
                image="contract:latest",
                state="running",
                status="Up 5 minutes",
                project_id="project-1",
                project_name="合同服务",
                project_kind="backend",
                ports=[],
            )
        ]

    def read_log_snapshot(self, workspace_id: str, container_id: str, **_: object):
        assert workspace_id == "workspace-1"
        assert container_id == "a" * 64
        return ContainerLogSnapshot(records=self.records, truncated=False)


def _service(records: list[ContainerLogRecord]):
    repository = InMemoryAiLogInvestigationRepository()
    return (
        AiLogVisualizationService(
            records=repository,
            tasks=_Tasks(),  # type: ignore[arg-type]
            projects=_Projects(),  # type: ignore[arg-type]
            workspaces=_Workspaces(),  # type: ignore[arg-type]
            containers=_Containers(records),  # type: ignore[arg-type]
        ),
        repository,
    )


def test_inspection_records_redacted_error_and_is_idempotent() -> None:
    service, repository = _service(
        [
            ContainerLogRecord("stdout", "request started", "2026-08-24T01:00:00Z"),
            ContainerLogRecord(
                "stderr",
                "ConnectTimeoutError password=plain-secret",
                "2026-08-24T01:00:01Z",
            ),
            ContainerLogRecord("stderr", "Traceback: call failed", "2026-08-24T01:00:02Z"),
        ]
    )

    first = service.inspect_container_errors(task_id=7, container_id="a" * 64)
    second = service.inspect_container_errors(task_id=7, container_id="a" * 64)

    assert first["status"] == "recorded"
    assert first["record_created"] is True
    assert second["record_created"] is False
    assert second["record"]["id"] == first["record"]["id"]  # type: ignore[index]
    stored = repository.list_records(workspace_id=None, severity=None, limit=10, offset=0)
    assert len(stored) == 1
    assert stored[0].error_title == "ConnectTimeoutError"
    assert "plain-secret" not in stored[0].error_excerpt
    assert "[REDACTED]" in stored[0].error_excerpt


def test_inspection_with_unmatched_keywords_does_not_record_other_errors() -> None:
    service, repository = _service(
        [
            ContainerLogRecord(
                "stderr",
                "ConnectTimeoutError while loading contracts",
                "2026-08-24T01:00:01Z",
            )
        ]
    )

    result = service.inspect_container_errors(
        task_id=7,
        container_id="a" * 64,
        keywords=["payment"],
    )

    assert result["status"] == "no_errors"
    assert (
        repository.list_records(
            workspace_id=None,
            severity=None,
            limit=10,
            offset=0,
        )
        == []
    )


def test_inspection_does_not_record_when_no_error_is_found() -> None:
    service, repository = _service(
        [ContainerLogRecord("stdout", "service is ready", "2026-08-24T01:00:00Z")]
    )

    result = service.inspect_container_errors(task_id=7, container_id="a" * 64)

    assert result["status"] == "no_errors"
    assert repository.list_records(workspace_id=None, severity=None, limit=10, offset=0) == []


def test_inspection_rejects_unregistered_container() -> None:
    service, _ = _service([])

    with pytest.raises(AiLogVisualizationError, match="未在当前"):
        service.inspect_container_errors(task_id=7, container_id="b" * 64)
