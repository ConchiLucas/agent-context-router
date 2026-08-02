import pytest

from context_router.repositories.runtime_config_repository import (
    InMemoryRuntimeConfigRepository,
)
from context_router.repositories.workspace_deploy_repository import (
    InMemoryWorkspaceDeployRepository,
    WorkspaceDeployRepositoryError,
)
from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
    WorkspaceRuntimeFileDraft,
    WorkspaceRuntimePolicyDraft,
)
from context_router.schemas.workspace_deploy_sync import (
    DeployConfigFile,
    ProjectDeployBundle,
    RuntimeProfileBundle,
    WorkspaceDeployBundle,
)


def _profile(content: str) -> RuntimeProfileBundle:
    return RuntimeProfileBundle(files=(DeployConfigFile("deploy.sh", content, True),))


def _bundle(content: str = "new") -> WorkspaceDeployBundle:
    return WorkspaceDeployBundle(
        digest="a" * 64,
        workspace_paths=("deploy",),
        project_order=("backend",),
        start=_profile(f"#!/bin/sh\necho {content}-workspace\n"),
        projects=(
            ProjectDeployBundle(
                project_id="backend",
                relative_path="backend",
                fast=_profile(f"#!/bin/sh\necho {content}-fast\n"),
                full=_profile(f"#!/bin/sh\necho {content}-full\n"),
            ),
        ),
    )


def test_workspace_runtime_files_are_replaced_in_stable_order() -> None:
    repository = InMemoryWorkspaceRuntimeRepository()

    records = repository.replace_files(
        "workspace-1",
        "start",
        [
            WorkspaceRuntimeFileDraft("deploy.sh", "#!/bin/sh\n", True),
            WorkspaceRuntimeFileDraft("compose.yaml", "services: {}\n", False),
        ],
    )

    assert [record.relative_path for record in records] == ["deploy.sh", "compose.yaml"]
    assert repository.list_files("workspace-1", "start") == records
    replacement = repository.replace_files(
        "workspace-1",
        "start",
        [WorkspaceRuntimeFileDraft("deploy.sh", "#!/bin/sh\nexit 0\n", True)],
    )
    assert [record.relative_path for record in replacement] == ["deploy.sh"]


def test_workspace_runtime_policy_round_trips_without_machine_secrets() -> None:
    repository = InMemoryWorkspaceRuntimeRepository()

    saved = repository.save_policy(
        "workspace-1",
        WorkspaceRuntimePolicyDraft(
            project_order=("backend", "frontend"),
            workspace_paths=("deploy-compose-full.sh", ".env.example"),
        ),
    )

    assert repository.get_policy("workspace-1") == saved
    assert saved.project_order == ("backend", "frontend")
    assert ".env.local" not in saved.workspace_paths


def test_workspace_deploy_repository_replaces_complete_bundle() -> None:
    workspace_runtime = InMemoryWorkspaceRuntimeRepository()
    project_runtime = InMemoryRuntimeConfigRepository()
    repository = InMemoryWorkspaceDeployRepository(
        workspace_runtime=workspace_runtime,
        project_runtime=project_runtime,
    )

    repository.replace_workspace_bundle("workspace-1", _bundle())

    assert "new-workspace" in workspace_runtime.list_files("workspace-1", "start")[0].content
    assert workspace_runtime.get_policy("workspace-1").project_order == ("backend",)
    assert "new-fast" in project_runtime.list_files("backend", "fast")[0].content
    assert "new-full" in project_runtime.list_files("backend", "full")[0].content


def test_workspace_deploy_repository_preserves_old_bundle_when_validation_fails() -> None:
    workspace_runtime = InMemoryWorkspaceRuntimeRepository()
    project_runtime = InMemoryRuntimeConfigRepository()
    repository = InMemoryWorkspaceDeployRepository(
        workspace_runtime=workspace_runtime,
        project_runtime=project_runtime,
    )
    repository.replace_workspace_bundle("workspace-1", _bundle("old"))
    invalid = WorkspaceDeployBundle(
        digest="b" * 64,
        workspace_paths=("deploy",),
        project_order=("backend",),
        start=_profile("#!/bin/sh\necho invalid\n"),
        projects=(
            ProjectDeployBundle(
                project_id="backend",
                relative_path="backend",
                fast=RuntimeProfileBundle(
                    files=(
                        DeployConfigFile("deploy.sh", "#!/bin/sh\n", True),
                        DeployConfigFile("deploy.sh", "#!/bin/sh\n", True),
                    )
                ),
                full=_profile("#!/bin/sh\necho invalid\n"),
            ),
        ),
    )

    with pytest.raises(WorkspaceDeployRepositoryError, match="重复"):
        repository.replace_workspace_bundle("workspace-1", invalid)

    assert "old-workspace" in workspace_runtime.list_files("workspace-1", "start")[0].content
    assert "old-fast" in project_runtime.list_files("backend", "fast")[0].content
    assert "old-full" in project_runtime.list_files("backend", "full")[0].content
