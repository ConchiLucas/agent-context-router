from datetime import UTC, datetime
from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.repositories.workspace_repository import (
    InMemoryWorkspaceRepository,
    WorkspaceRecord,
)
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError


def write_document(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_workspace_refresh_replaces_old_document_cache(tmp_path: Path) -> None:
    root = tmp_path / "AGENTS.md"
    old_document = tmp_path / "docs" / "old.md"
    new_document = tmp_path / "docs" / "new.md"
    write_document(old_document, "# 旧文档")
    write_document(new_document, "# 新文档")
    write_document(
        root,
        """
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 旧文档 | `./docs/old.md` |
""".strip(),
    )

    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        )
    )
    project = registry.add_project(name="测试项目", agents_path=str(root))
    assert project.workspace_id is not None
    old_id = registry.get_workspace_tree(project.workspace_id).children[0].id

    write_document(
        root,
        """
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 新文档 | `./docs/new.md` |
""".strip(),
    )
    registry.refresh_workspace(project.workspace_id)

    tree = registry.get_workspace_tree(project.workspace_id)
    assert [child.description for child in tree.children] == ["新文档"]
    with pytest.raises(ProjectRegistryError, match="不在当前工作空间映射"):
        registry.get_workspace_document(project.workspace_id, old_id)


def test_project_configuration_survives_registry_recreation(tmp_path: Path) -> None:
    root = tmp_path / "project" / "AGENTS.md"
    write_document(root, "# 项目入口")
    settings = Settings(
        workspace_host_root=tmp_path,
        workspace_container_root=tmp_path,
    )
    repository = InMemoryProjectRepository()
    first_registry = ProjectRegistry(settings, repository)
    created = first_registry.add_project(name="原项目", agents_path=str(root))
    assert created.project_type == "公司项目"
    assert created.project_kind == "backend"
    assert not hasattr(first_registry, "set_project_enabled")

    second_registry = ProjectRegistry(settings, repository)
    restored = second_registry.load_persisted_projects()

    assert len(restored) == 1
    assert restored[0].id == created.id
    assert restored[0].node_count == 1

    updated = second_registry.update_project(
        created.id,
        name="新项目名",
        project_type="业务系统",
        project_kind="frontend",
        agents_path=str(root),
    )
    assert updated.name == "新项目名"
    assert updated.project_type == "业务系统"
    assert updated.project_kind == "frontend"

    third_registry = ProjectRegistry(settings, repository)
    reloaded = third_registry.load_persisted_projects()
    assert [
        (project.id, project.name, project.project_type, project.project_kind)
        for project in reloaded
    ] == [(created.id, "新项目名", "业务系统", "frontend")]

    third_registry.delete_project(created.id)
    assert ProjectRegistry(settings, repository).load_persisted_projects() == []


def test_missing_persisted_project_path_is_retained_with_error(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing" / "AGENTS.md"
    repository = InMemoryProjectRepository()
    repository.create_project(
        project_id="persisted-project",
        name="路径失效项目",
        agents_path=str(missing_root),
    )
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        ),
        repository,
    )

    restored = registry.load_persisted_projects()

    assert restored[0].id == "persisted-project"
    assert restored[0].node_count == 0
    assert "找不到入口文件" in (restored[0].error or "")


def test_disabled_nested_workspace_does_not_fall_back_to_parent(tmp_path: Path) -> None:
    parent_root = tmp_path / "workspace" / "AGENTS.md"
    nested_root = tmp_path / "workspace" / "services" / "order" / "AGENTS.md"
    write_document(parent_root, "# 根项目")
    write_document(nested_root, "# 订单项目")
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=tmp_path,
            workspace_container_root=tmp_path,
        )
    )
    registry.add_project(name="根项目", agents_path=str(parent_root))
    nested = registry.add_project(name="订单项目", agents_path=str(nested_root))
    assert nested.workspace_id is not None
    registry.apply_workspace_record(
        WorkspaceRecord(
            id=nested.workspace_id,
            name=nested.workspace_name or nested.name,
            workspace_type=nested.project_type,
            root_path=str(nested_root.parent),
            enabled=False,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )

    with pytest.raises(ProjectRegistryError, match="工作空间已停用"):
        registry.find_workspace_for_cwd(str(nested_root.parent / "src"))


def test_missing_nested_project_does_not_fall_back_after_workspace_reload(
    tmp_path: Path,
) -> None:
    host_root = tmp_path / "host"
    container_root = tmp_path / "container"
    workspace_host_root = host_root / "workspace"
    parent_root = container_root / "workspace" / "AGENTS.md"
    nested_root = container_root / "workspace" / "services" / "order" / "AGENTS.md"
    write_document(parent_root, "# 根项目")
    write_document(nested_root, "# 订单项目")

    workspace_repository = InMemoryWorkspaceRepository()
    workspace_repository.create_workspace(
        workspace_id="workspace-id",
        name="测试工作空间",
        workspace_type="公司项目",
        root_path=str(workspace_host_root),
        enabled=True,
    )
    project_repository = InMemoryProjectRepository(workspace_repository)
    registry = ProjectRegistry(
        Settings(
            workspace_host_root=host_root,
            workspace_container_root=container_root,
        ),
        project_repository,
    )
    workspace = workspace_repository.get_workspace("workspace-id")
    registry.add_workspace_project(
        workspace,
        name="根项目",
        relative_path=".",
    )
    registry.add_workspace_project(
        workspace,
        name="订单项目",
        relative_path="services/order",
    )

    nested_root.unlink()
    registry.apply_workspace_record(workspace)

    snapshot = registry.find_workspace_for_cwd(
        str(workspace_host_root / "services" / "order" / "src")
    )
    assert snapshot.active_project is not None
    assert snapshot.active_project.name == "订单项目"
    cached_root = snapshot.active_project.cache.root
    assert "# 订单项目" in snapshot.active_project.cache.documents[cached_root.id].content
    assert "找不到入口文件" in (
        registry.get_project_summary(snapshot.active_project.id).error or ""
    )
