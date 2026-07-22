from pathlib import Path

import pytest

from context_router.config import Settings
from context_router.repositories.project_repository import InMemoryProjectRepository
from context_router.services.project_registry import ProjectRegistry, ProjectRegistryError


def write_document(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_refresh_replaces_old_document_cache(tmp_path: Path) -> None:
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
    old_id = registry.get_tree(project.id).children[0].id

    write_document(
        root,
        """
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 新文档 | `./docs/new.md` |
""".strip(),
    )
    registry.refresh_project(project.id)

    tree = registry.get_tree(project.id)
    assert [child.description for child in tree.children] == ["新文档"]
    with pytest.raises(ProjectRegistryError, match="不在当前内存映射"):
        registry.get_document(project.id, old_id)


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
    first_registry.set_project_enabled(created.id, enabled=False)

    second_registry = ProjectRegistry(settings, repository)
    restored = second_registry.load_persisted_projects()

    assert len(restored) == 1
    assert restored[0].id == created.id
    assert restored[0].enabled is False
    assert restored[0].node_count == 0

    enabled = second_registry.set_project_enabled(created.id, enabled=True)
    assert enabled.enabled is True
    assert enabled.node_count == 1

    updated = second_registry.update_project(
        created.id,
        name="新项目名",
        project_type="业务系统",
        agents_path=str(root),
    )
    assert updated.name == "新项目名"
    assert updated.project_type == "业务系统"

    third_registry = ProjectRegistry(settings, repository)
    reloaded = third_registry.load_persisted_projects()
    assert [
        (project.id, project.name, project.project_type, project.enabled) for project in reloaded
    ] == [(created.id, "新项目名", "业务系统", True)]

    third_registry.delete_project(created.id)
    assert ProjectRegistry(settings, repository).load_persisted_projects() == []


def test_missing_persisted_project_path_is_retained_with_error(tmp_path: Path) -> None:
    missing_root = tmp_path / "missing" / "AGENTS.md"
    repository = InMemoryProjectRepository()
    repository.create_project(
        project_id="persisted-project",
        name="路径失效项目",
        agents_path=str(missing_root),
        enabled=True,
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
    assert restored[0].enabled is True
    assert restored[0].node_count == 0
    assert "找不到入口文件" in (restored[0].error or "")
