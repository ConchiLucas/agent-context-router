from __future__ import annotations

from pathlib import Path

import pytest

from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.runtime_config_repository import InMemoryRuntimeConfigRepository
from context_router.repositories.workspace_deploy_repository import (
    InMemoryWorkspaceDeployRepository,
)
from context_router.repositories.workspace_repository import InMemoryWorkspaceRepository
from context_router.repositories.workspace_runtime_repository import (
    InMemoryWorkspaceRuntimeRepository,
)
from context_router.services.workspace_deploy_sync import (
    WorkspaceDeploySyncError,
    WorkspaceDeploySyncService,
    scan_workspace_deploy_bundle,
)


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _workspace(tmp_path: Path) -> tuple[Path, list[object]]:
    root = tmp_path / "workspace"
    _write(root / "docs/backend/AGENTS.md", "# Backend\n")
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-1",
        name="Workspace",
        root_path=str(root),
    )
    project_repository = InMemoryProjectRepository(workspace_repository)
    project_repository.create_project(
        project_id="backend-1",
        name="Backend",
        workspace_id="workspace-1",
        relative_path="backend",
        document_relative_path="docs/backend/AGENTS.md",
    )
    return root, list(project_repository.list_projects("workspace-1"))


def _canonical_tree(root: Path) -> None:
    _write(
        root / "deploy/context-router/manifest.yaml",
        """schema_version: 1
workspace:
  workspace_paths:
    - deploy
    - docker-compose.yml
project_order:
  - backend
""",
    )
    _write(
        root / "deploy/context-router/workspace/start/deploy.sh",
        "#!/bin/sh\nexit 0\n",
        executable=True,
    )
    _write(
        root / "deploy/context-router/workspace/start/compose.yaml",
        "services: {}\n",
    )
    for mode in ("fast", "full"):
        _write(
            root / f"backend/deploy/context-router/{mode}/deploy.sh",
            "#!/bin/sh\nexit 0\n",
            executable=True,
        )


def test_scan_workspace_deploy_bundle_reads_fixed_layout_and_stable_digest(
    tmp_path: Path,
) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)

    first = scan_workspace_deploy_bundle(root, projects)
    second = scan_workspace_deploy_bundle(root, projects)

    assert first.digest == second.digest
    assert len(first.digest) == 64
    assert first.workspace_paths == ("deploy", "docker-compose.yml")
    assert first.project_order == ("backend-1",)
    assert [item.relative_path for item in first.start.files] == [
        "compose.yaml",
        "deploy.sh",
    ]
    assert first.start.files[1].executable is True
    assert [(item.project_id, item.relative_path) for item in first.projects] == [
        ("backend-1", "backend")
    ]
    assert [item.relative_path for item in first.projects[0].fast.files] == ["deploy.sh"]
    assert [item.relative_path for item in first.projects[0].full.files] == ["deploy.sh"]


def test_scan_workspace_deploy_bundle_rejects_missing_project_profile(
    tmp_path: Path,
) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)
    (root / "backend/deploy/context-router/full/deploy.sh").unlink()

    with pytest.raises(WorkspaceDeploySyncError, match="full.*deploy.sh"):
        scan_workspace_deploy_bundle(root, projects)


@pytest.mark.parametrize(
    "relative_path",
    [".env.local", "id_rsa", "server.key", "credentials.json"],
)
def test_scan_workspace_deploy_bundle_rejects_secret_files(
    tmp_path: Path,
    relative_path: str,
) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)
    _write(
        root / "backend/deploy/context-router/fast" / relative_path,
        "secret\n",
    )

    with pytest.raises(WorkspaceDeploySyncError, match="敏感文件"):
        scan_workspace_deploy_bundle(root, projects)


def test_scan_workspace_deploy_bundle_rejects_symlinks(tmp_path: Path) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)
    outside = tmp_path / "outside.sh"
    _write(outside, "#!/bin/sh\n", executable=True)
    (root / "backend/deploy/context-router/fast/linked.sh").symlink_to(outside)

    with pytest.raises(WorkspaceDeploySyncError, match="符号链接"):
        scan_workspace_deploy_bundle(root, projects)


def test_scan_workspace_deploy_bundle_rejects_manifest_symlink(tmp_path: Path) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)
    manifest = root / "deploy/context-router/manifest.yaml"
    outside = tmp_path / "manifest.yaml"
    manifest.replace(outside)
    manifest.symlink_to(outside)

    with pytest.raises(WorkspaceDeploySyncError, match="符号链接"):
        scan_workspace_deploy_bundle(root, projects)


def test_scan_workspace_deploy_bundle_rejects_project_symlink_escape(
    tmp_path: Path,
) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)
    project_root = root / "backend"
    outside = tmp_path / "outside-backend"
    project_root.replace(outside)
    project_root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspaceDeploySyncError, match="越出 Workspace"):
        scan_workspace_deploy_bundle(root, projects)


def test_scan_workspace_deploy_bundle_digest_changes_with_source_content(
    tmp_path: Path,
) -> None:
    root, projects = _workspace(tmp_path)
    _canonical_tree(root)
    before = scan_workspace_deploy_bundle(root, projects)

    _write(
        root / "backend/deploy/context-router/fast/deploy.sh",
        "#!/bin/sh\necho changed\n",
        executable=True,
    )

    after = scan_workspace_deploy_bundle(root, projects)
    assert after.digest != before.digest


def _service(
    tmp_path: Path,
) -> tuple[
    WorkspaceDeploySyncService,
    Path,
    InMemoryWorkspaceRuntimeRepository,
    InMemoryRuntimeConfigRepository,
]:
    root, _ = _workspace(tmp_path)
    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-1",
        name="Workspace",
        root_path=str(root),
    )
    project_repository = InMemoryProjectRepository(workspace_repository)
    project_repository.create_project(
        project_id="backend-1",
        name="Backend",
        workspace_id="workspace-1",
        relative_path="backend",
        document_relative_path="docs/backend/AGENTS.md",
    )
    workspace_runtime = InMemoryWorkspaceRuntimeRepository()
    project_runtime = InMemoryRuntimeConfigRepository()
    deploy_repository = InMemoryWorkspaceDeployRepository(
        workspace_runtime=workspace_runtime,
        project_runtime=project_runtime,
    )
    return (
        WorkspaceDeploySyncService(
            workspace_repository=workspace_repository,
            project_repository=project_repository,
            workspace_runtime_repository=workspace_runtime,
            project_runtime_repository=project_runtime,
            deploy_repository=deploy_repository,
        ),
        root,
        workspace_runtime,
        project_runtime,
    )


def test_workspace_deploy_sync_preview_reports_profile_changes(tmp_path: Path) -> None:
    service, root, _, _ = _service(tmp_path)
    _canonical_tree(root)

    preview = service.preview("workspace-1")

    assert preview.valid is True
    assert preview.source_root == str(root / "deploy/context-router")
    assert preview.total.additions == 4
    assert preview.total.updates == 0
    assert preview.total.deletions == 0
    assert [(item.owner, item.mode, item.file_count) for item in preview.profiles] == [
        ("workspace", "start", 2),
        ("backend", "fast", 1),
        ("backend", "full", 1),
    ]


def test_workspace_deploy_sync_commit_rejects_stale_digest_without_mutation(
    tmp_path: Path,
) -> None:
    service, root, workspace_runtime, project_runtime = _service(tmp_path)
    _canonical_tree(root)
    preview = service.preview("workspace-1")
    _write(
        root / "backend/deploy/context-router/fast/deploy.sh",
        "#!/bin/sh\necho changed\n",
        executable=True,
    )

    with pytest.raises(WorkspaceDeploySyncError) as caught:
        service.commit("workspace-1", preview.digest)

    assert caught.value.code == "deploy_sync_stale_preview"
    assert workspace_runtime.list_files("workspace-1", "start") == []
    assert project_runtime.list_files("backend-1", "fast") == []


def test_workspace_deploy_sync_commit_persists_current_bundle(tmp_path: Path) -> None:
    service, root, workspace_runtime, project_runtime = _service(tmp_path)
    _canonical_tree(root)
    preview = service.preview("workspace-1")

    result = service.commit("workspace-1", preview.digest)

    assert result.digest == preview.digest
    assert result.synchronized is True
    assert len(workspace_runtime.list_files("workspace-1", "start")) == 2
    assert len(project_runtime.list_files("backend-1", "fast")) == 1
    assert len(project_runtime.list_files("backend-1", "full")) == 1
