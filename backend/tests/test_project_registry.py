from pathlib import Path

import pytest

from context_router.config import Settings
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
