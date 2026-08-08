from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from context_router.config import Settings
from context_router.repositories.workspace_repository import WorkspaceRecord
from context_router.repositories.workspace_shared_file_repository import WorkspaceSharedFile
from context_router.services.local_workspace_mapping import LocalWorkspaceMappingService
from context_router.services.workspace_shared_files import WorkspaceSharedFilesService


class _WorkspaceRepository:
    def __init__(self, root: Path) -> None:
        now = datetime.now(UTC)
        self.record = WorkspaceRecord(
            id="workspace-1",
            name="Workspace",
            workspace_type="公司项目",
            root_path=str(root),
            created_at=now,
            updated_at=now,
        )

    def get_workspace(self, _: str) -> WorkspaceRecord:
        return self.record


class _ProjectRepository:
    def list_projects(self, *, workspace_id: str):
        assert workspace_id == "workspace-1"
        return [SimpleNamespace(id="project-1", relative_path=".")]


class _SharedFilesRepository:
    def __init__(self) -> None:
        self.files: list[WorkspaceSharedFile] = []
        self.bundle = None

    def list_files(self, _: str) -> list[WorkspaceSharedFile]:
        return list(self.files)

    def replace_all(self, workspace_id: str, files, deploy_bundle) -> None:
        assert workspace_id == "workspace-1"
        self.files = list(files)
        self.bundle = deploy_bundle


class _Registry:
    def __init__(self) -> None:
        self.refreshed: list[str] = []

    def refresh_workspace(self, workspace_id: str) -> None:
        self.refreshed.append(workspace_id)


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_publish_and_restore_replace_documents_and_deploy_files(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/AGENTS.md").write_text("# canonical", encoding="utf-8")
    deploy_root = tmp_path / "deploy/context-router"
    deploy_root.mkdir(parents=True)
    (deploy_root / "manifest.yaml").write_text(
        """schema_version: 1
project_order:
  - .
workspace:
  workspace_paths: []
""",
        encoding="utf-8",
    )
    _write_script(deploy_root / "workspace/start/deploy.sh", "#!/bin/sh\ntrue\n")
    _write_script(deploy_root / "fast/deploy.sh", "#!/bin/sh\necho fast\n")
    _write_script(deploy_root / "full/deploy.sh", "#!/bin/sh\necho full\n")

    settings = Settings(
        workspace_host_root=tmp_path,
        workspace_container_root=tmp_path,
        workspace_mapping_file=None,
    )
    files = _SharedFilesRepository()
    registry = _Registry()
    service = WorkspaceSharedFilesService(
        settings=settings,
        local_mapping=LocalWorkspaceMappingService(settings),
        workspace_repository=_WorkspaceRepository(tmp_path),
        project_repository=_ProjectRepository(),
        shared_file_repository=files,
        registry=registry,
    )

    published = service.publish("workspace-1")
    assert published.document_count == 1
    assert published.deploy_count == 4
    assert files.bundle is not None

    (tmp_path / "docs/AGENTS.md").write_text("# changed", encoding="utf-8")
    (tmp_path / "docs/extra.md").write_text("remove me", encoding="utf-8")
    (deploy_root / "fast/deploy.sh").write_text("changed", encoding="utf-8")

    restored = service.restore("workspace-1")
    assert restored.document_count == 1
    assert (tmp_path / "docs/AGENTS.md").read_text(encoding="utf-8") == "# canonical"
    assert not (tmp_path / "docs/extra.md").exists()
    assert (deploy_root / "fast/deploy.sh").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho fast\n"
    )
    assert registry.refreshed == ["workspace-1"]
