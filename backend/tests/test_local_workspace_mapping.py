from datetime import UTC, datetime
from pathlib import Path

from context_router.config import Settings
from context_router.repositories.workspace_repository import WorkspaceRecord
from context_router.services.context_preparation import ContextPreparationService
from context_router.services.local_workspace_mapping import LocalWorkspaceMappingService
from context_router.services.project_registry import ProjectRegistry


class _TaskRepository:
    def create_workspace_task(self, **_: object) -> int:
        return 7


def _mapping_file(tmp_path: Path) -> Path:
    path = tmp_path / "workspaces.local.yaml"
    path.write_text(
        """
version: 1
workspaces:
  workspace-1:
    visible: true
    main_path: main
    document_reader_paths:
      - branch-copy
  workspace-2:
    visible: false
    main_path: hidden
    document_reader_paths: []
""".strip(),
        encoding="utf-8",
    )
    return path


def _record(workspace_id: str, root_path: str = "/old/database/path") -> WorkspaceRecord:
    now = datetime.now(UTC)
    return WorkspaceRecord(
        id=workspace_id,
        name=workspace_id,
        workspace_type="公司项目",
        root_path=root_path,
        created_at=now,
        updated_at=now,
    )


def test_local_mapping_controls_visibility_and_machine_paths(tmp_path: Path) -> None:
    mapping = LocalWorkspaceMappingService(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
            workspace_mapping_file=_mapping_file(tmp_path),
        )
    )

    mapped = mapping.map_record(_record("workspace-1"))
    assert mapped is not None
    assert mapped.root_path == str(tmp_path / "main")
    assert mapping.map_record(_record("workspace-2")) is None
    assert mapping.reader_count("workspace-1") == 1


def test_reader_path_prepares_documents_only_context(tmp_path: Path) -> None:
    main_root = tmp_path / "main"
    reader_root = tmp_path / "branch-copy"
    main_root.mkdir()
    reader_root.mkdir()
    (main_root / "AGENTS.md").write_text("# 主目录文档", encoding="utf-8")
    settings = Settings(
        workspace_host_root=tmp_path,
        workspace_container_root=tmp_path,
        workspace_mapping_file=_mapping_file(tmp_path),
    )
    mapping = LocalWorkspaceMappingService(settings)
    registry = ProjectRegistry(settings, local_mapping=mapping)
    mapped = mapping.map_record(_record("workspace-1"))
    assert mapped is not None
    registry.register_workspace(mapped)

    snapshot = registry.find_workspace_for_cwd(str(reader_root / "src"))
    assert snapshot.access_mode == "documents_only"
    result = ContextPreparationService(registry, _TaskRepository()).prepare(
        task="阅读文档",
        cwd=str(reader_root),
    )
    assert result.access == ["documents"]
    assert result.warnings == ["当前目录共享主工作空间文档；数据库和部署工具不可用"]
