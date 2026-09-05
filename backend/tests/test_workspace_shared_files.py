import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from context_router.config import Settings
from context_router.repositories.workspace_repository import WorkspaceRecord
from context_router.repositories.workspace_shared_file_repository import (
    WorkspaceSharedFileSet,
    shared_file_set_digest,
)
from context_router.services.local_workspace_mapping import LocalWorkspaceMappingService
from context_router.services.project_registry import ProjectRegistryError
from context_router.services.workspace_shared_files import (
    WorkspaceSharedFilesError,
    WorkspaceSharedFilesService,
)


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
        self.file_set: WorkspaceSharedFileSet | None = None
        self.bundle = None

    def get_file_set(self, _: str, revision: int | None = None) -> WorkspaceSharedFileSet | None:
        if self.file_set is None:
            return None
        if revision is not None and revision != self.file_set.revision:
            return None
        return self.file_set

    def replace_all(self, workspace_id: str, files, deploy_bundle) -> WorkspaceSharedFileSet:
        assert workspace_id == "workspace-1"
        if deploy_bundle is not None:
            self.bundle = deploy_bundle
        revision = self.file_set.revision + 1 if self.file_set else 1
        self.file_set = WorkspaceSharedFileSet(
            revision=revision,
            digest=shared_file_set_digest(files),
            files=tuple(files),
        )
        return self.file_set


class _Registry:
    def __init__(self) -> None:
        self.refreshed: list[str] = []
        self.fail = False

    def refresh_workspace(self, workspace_id: str) -> None:
        if self.fail:
            raise ProjectRegistryError("refresh failed")
        self.refreshed.append(workspace_id)


def _write_script(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _write_fixture(tmp_path: Path) -> None:
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
    _write_script(tmp_path / "script/deploy.sh", "#!/bin/sh\necho workspace\n")
    _write_script(tmp_path / "deploy/host-runtime/ensure.sh", "#!/bin/sh\ntrue\n")


def _build_service(
    tmp_path: Path, *, files: _SharedFilesRepository
) -> tuple[WorkspaceSharedFilesService, _Registry]:
    settings = Settings(
        workspace_host_root=tmp_path,
        workspace_container_root=tmp_path,
        workspace_mapping_file=None,
    )
    registry = _Registry()
    service = WorkspaceSharedFilesService(
        settings=settings,
        local_mapping=LocalWorkspaceMappingService(settings),
        workspace_repository=_WorkspaceRepository(tmp_path),
        project_repository=_ProjectRepository(),
        shared_file_repository=files,
        registry=registry,
    )
    return service, registry


def test_publish_and_restore_replace_documents_and_deploy_files(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    deploy_root = tmp_path / "deploy/context-router"
    files = _SharedFilesRepository()
    service, registry = _build_service(tmp_path, files=files)

    published = service.publish("workspace-1")
    assert published.document_count == 1
    assert published.deploy_count == 4
    assert published.script_count == 1
    assert published.host_runtime_count == 1
    assert published.revision == 1
    assert files.bundle is not None

    (tmp_path / "docs/AGENTS.md").write_text("# changed", encoding="utf-8")
    (tmp_path / "docs/extra.md").write_text("remove me", encoding="utf-8")
    (deploy_root / "fast/deploy.sh").write_text("changed", encoding="utf-8")
    (tmp_path / "script/deploy.sh").write_text("#!/bin/sh\nfalse\n", encoding="utf-8")
    (tmp_path / "deploy/host-runtime/ensure.sh").write_text("#!/bin/sh\nfalse\n", encoding="utf-8")
    host_runtime_inode = (tmp_path / "deploy/host-runtime").stat().st_ino
    host_script_inode = (tmp_path / "deploy/host-runtime/ensure.sh").stat().st_ino
    (tmp_path / "deploy/host-runtime/stale.sh").write_text("#!/bin/sh\ntrue\n", encoding="utf-8")

    restored = service.restore("workspace-1")
    assert restored.document_count == 1
    assert (tmp_path / "docs/AGENTS.md").read_text(encoding="utf-8") == "# canonical"
    assert not (tmp_path / "docs/extra.md").exists()
    assert (deploy_root / "fast/deploy.sh").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho fast\n"
    )
    assert (tmp_path / "script/deploy.sh").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho workspace\n"
    )
    assert (tmp_path / "deploy/host-runtime/ensure.sh").read_text(encoding="utf-8") == (
        "#!/bin/sh\ntrue\n"
    )
    assert (tmp_path / "deploy/host-runtime").stat().st_ino == host_runtime_inode
    assert (tmp_path / "deploy/host-runtime/ensure.sh").stat().st_ino == host_script_inode
    assert not (tmp_path / "deploy/host-runtime/stale.sh").exists()
    assert restored.revision == 1
    assert len(restored.digest) == 64
    state = json.loads((tmp_path / "deploy/runtime/context-router-shared-files.json").read_text())
    assert state["revision"] == 1
    assert registry.refreshed == ["workspace-1"]

    (tmp_path / "script/deploy.sh").write_text("#!/bin/sh\nfalse\n", encoding="utf-8")
    synchronized = service.synchronize_if_stale("workspace-1")
    assert synchronized is not None
    assert (tmp_path / "script/deploy.sh").read_text(encoding="utf-8") == (
        "#!/bin/sh\necho workspace\n"
    )

    assert service.synchronize_if_stale("workspace-1") is None

    (tmp_path / "docs/AGENTS.md").write_text("# keep after rollback", encoding="utf-8")
    registry.fail = True
    with pytest.raises(WorkspaceSharedFilesError, match="已回滚"):
        service.restore("workspace-1")
    assert (tmp_path / "docs/AGENTS.md").read_text(encoding="utf-8") == ("# keep after rollback")


def test_publish_runtime_files_retains_database_documents_and_deploy(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    (tmp_path / "script/.DS_Store").write_bytes(b"\x00\xffmacOS metadata")
    (tmp_path / "script/tool/dist").mkdir(parents=True)
    (tmp_path / "script/tool/dist/tool-bin").write_bytes(b"\x00\xffcompiled")
    files = _SharedFilesRepository()
    service, _ = _build_service(tmp_path, files=files)
    published = service.publish("workspace-1")

    (tmp_path / "docs/AGENTS.md").write_text("# local-only", encoding="utf-8")
    (tmp_path / "script/deploy.sh").write_text("#!/bin/sh\necho updated\n", encoding="utf-8")
    runtime_published = service.publish_runtime_files("workspace-1")

    assert runtime_published.revision == published.revision + 1
    assert files.bundle is not None
    current = files.get_file_set("workspace-1")
    assert current is not None
    contents = {item.relative_path: item.content for item in current.files}
    assert contents["docs/AGENTS.md"] == "# canonical"
    assert contents["script/deploy.sh"] == "#!/bin/sh\necho updated\n"
    assert "script/.DS_Store" not in contents
    assert "script/tool/dist/tool-bin" not in contents
