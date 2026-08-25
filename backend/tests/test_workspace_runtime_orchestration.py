from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from context_router.repositories.runtime_config_repository import (
    InMemoryRuntimeConfigRepository,
    RuntimeConfigFileDraft,
)
from context_router.repositories.runtime_operation_repository import (
    InMemoryRuntimeOperationRepository,
)
from context_router.repositories.task_repository import TaskRecord
from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
    WorkspaceRuntimeFileDraft,
    WorkspaceRuntimePolicyDraft,
)
from context_router.services.runtime_materialization import RuntimeMaterializationService
from context_router.services.workspace_runtime_orchestration import (
    WorkspaceRuntimeOrchestrationError,
    WorkspaceRuntimeOrchestrationService,
)


class FakeTasks:
    def __init__(self, intent_type: str = "task_execute") -> None:
        self.intent_type = intent_type

    def get_task(self, task_id: int) -> TaskRecord:
        assert task_id == 7
        return TaskRecord(
            id=7,
            project_id="api",
            project_key="workspace-key",
            project_name="API",
            task="change",
            cwd="/workspace/services/api",
            agent_name="codex",
            created_at=datetime.now(UTC),
            scope="workspace",
            workspace_id="workspace1",
            workspace_key="workspace-key",
            workspace_name="Workspace",
            active_project_id="api",
            active_project_name="API",
            active_project_kind="backend",
            intent_type=self.intent_type,  # type: ignore[arg-type]
        )


class FakeRegistry:
    def __init__(self, root: Path) -> None:
        self.snapshot = SimpleNamespace(
            id="workspace1",
            workspace_key="workspace-key",
            access_mode="full",
            root_path=str(root),
            resolved_root_path=root,
            projects=(
                SimpleNamespace(
                    id="root",
                    relative_path=".",
                    project_kind="frontend",
                ),
                SimpleNamespace(
                    id="admin",
                    relative_path="apps/admin",
                    project_kind="frontend",
                ),
                SimpleNamespace(
                    id="api",
                    relative_path="services/api",
                    project_kind="backend",
                ),
            ),
        )

    def get_workspace_snapshot_for_task(self, **_: object) -> object:
        return self.snapshot

    def get_workspace_snapshot(self, workspace_id: str) -> object:
        assert workspace_id == self.snapshot.id
        return self.snapshot


def build_service(
    tmp_path: Path,
    *,
    intent_type: str = "task_execute",
) -> WorkspaceRuntimeOrchestrationService:
    workspace_root = tmp_path / "workspace"
    for relative in ("apps/admin/src", "services/api", "shared"):
        (workspace_root / relative).mkdir(parents=True)
    project_configs = InMemoryRuntimeConfigRepository()
    for project_id in ("root", "admin", "api"):
        for mode in ("fast", "full"):
            project_configs.replace_files(
                project_id,
                mode,
                [RuntimeConfigFileDraft("deploy.sh", "#!/bin/sh\nexit 0\n", True)],
            )
    workspace_configs = InMemoryWorkspaceRuntimeRepository()
    workspace_configs.replace_files(
        "workspace1",
        "start",
        [WorkspaceRuntimeFileDraft("deploy.sh", "#!/bin/sh\nexit 0\n", True)],
    )
    workspace_configs.save_policy(
        "workspace1",
        WorkspaceRuntimePolicyDraft(
            project_order=("api", "admin", "root"),
            workspace_paths=("deploy-compose-full.sh", ".env.example", "shared"),
        ),
    )
    return WorkspaceRuntimeOrchestrationService(
        task_repository=FakeTasks(intent_type),
        registry=FakeRegistry(workspace_root),
        project_config_repository=project_configs,
        workspace_runtime_repository=workspace_configs,
        operation_repository=InMemoryRuntimeOperationRepository(),
        materialization_service=RuntimeMaterializationService(tmp_path / "runtime"),
    )


def test_routes_nested_projects_by_longest_prefix_and_policy_order(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    operation = service.apply_changes(
        task_id=7,
        changed_files=["apps/admin/src/page.tsx", "services/api/main.py"],
    )

    assert [(step.owner_id, step.mode) for step in operation.steps] == [
        ("api", "fast"),
        ("admin", "fast"),
    ]


def test_workspace_path_routes_to_one_start_step(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    operation = service.apply_changes(task_id=7, changed_files=["shared/helper.sh"])

    assert [(step.owner_type, step.mode) for step in operation.steps] == [("workspace", "start")]


def test_dependency_file_promotes_project_to_full(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    operation = service.apply_changes(
        task_id=7,
        changed_files=["services/api/main.py", "services/api/pyproject.toml"],
    )

    assert operation.steps[0].mode == "full"


def test_rejects_unsafe_or_unmapped_changed_paths(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    with pytest.raises(WorkspaceRuntimeOrchestrationError, match="相对路径"):
        service.apply_changes(task_id=7, changed_files=["../outside.py"])

    isolated = tmp_path / "isolated"
    isolated.mkdir()
    service._registry.snapshot.projects = (  # type: ignore[attr-defined]
        SimpleNamespace(id="api", relative_path="services/api", project_kind="backend"),
    )
    with pytest.raises(WorkspaceRuntimeOrchestrationError, match="没有归属"):
        service.apply_changes(task_id=7, changed_files=["isolated/file.py"])


def test_start_workspace_always_creates_one_workspace_start_step(tmp_path: Path) -> None:
    service = build_service(tmp_path)

    operation = service.start_workspace(task_id=7)

    assert operation.kind == "start_workspace"
    assert [(step.owner_type, step.mode) for step in operation.steps] == [("workspace", "start")]


def test_bug_investigation_intent_rejects_runtime_mutations(tmp_path: Path) -> None:
    service = build_service(tmp_path, intent_type="bug_investigate")

    with pytest.raises(WorkspaceRuntimeOrchestrationError) as apply_error:
        service.apply_changes(task_id=7, changed_files=["services/api/main.py"])
    with pytest.raises(WorkspaceRuntimeOrchestrationError) as start_error:
        service.start_workspace(task_id=7)

    assert apply_error.value.code == "intent_mutation_forbidden"
    assert start_error.value.code == "intent_mutation_forbidden"


def test_host_action_is_allowlisted_and_defaults_to_local(tmp_path: Path, monkeypatch) -> None:
    service = build_service(tmp_path)
    monkeypatch.setattr(
        "context_router.services.workspace_runtime_orchestration.PZH_WORKSPACE_ROOT",
        service._registry.snapshot.resolved_root_path,  # type: ignore[attr-defined]
    )

    operation = service.run_host_action(workspace_id="workspace1")

    assert operation.kind == "host_action"
    assert operation.environment == "local"
    assert operation.action == "pzh.ensure-host-runtime"
    assert [(step.owner_type, step.mode) for step in operation.steps] == [("workspace", "host")]
