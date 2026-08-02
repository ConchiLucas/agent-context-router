from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
    WorkspaceRuntimeFileDraft,
    WorkspaceRuntimePolicyDraft,
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
