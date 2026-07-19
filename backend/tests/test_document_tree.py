from pathlib import Path

import pytest

from context_router.services.document_tree import DocumentTreeError, build_document_cache


def write_document(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_builds_recursive_tree_and_caches_full_content(tmp_path: Path) -> None:
    root = tmp_path / "AGENTS.md"
    child = tmp_path / "docs" / "backend" / "overview.md"
    leaf = tmp_path / "docs" / "backend" / "api" / "api.md"

    write_document(
        root,
        """
# AGENTS.md

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 后端总览 | `./docs/backend/overview.md` |
""".strip(),
    )
    write_document(
        child,
        """
# 后端总览

## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| API 文档 | `./api/api.md` |
""".strip(),
    )
    write_document(leaf, "# API 文档\n\n完整的 Markdown 内容。")

    cache = build_document_cache(root)

    assert cache.root.children[0].children[0].description == "API 文档"
    leaf_id = cache.root.children[0].children[0].id
    assert cache.documents[leaf_id].content.endswith("完整的 Markdown 内容。")


def test_ignores_markdown_links_outside_child_table(tmp_path: Path) -> None:
    root = tmp_path / "AGENTS.md"
    write_document(root, "# AGENTS.md\n\n参考 [其他文档](./docs/other.md)。")

    cache = build_document_cache(root)

    assert cache.root.children == []
    assert len(cache.documents) == 1


def test_rejects_child_path_outside_current_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    root = project / "AGENTS.md"
    write_document(
        root,
        """
## 下级文档

| 功能说明 | 相对路径 |
| --- | --- |
| 外部文档 | `./nested/../../outside.md` |
""".strip(),
    )
    write_document(tmp_path / "outside.md", "# outside")

    cache = build_document_cache(root)

    assert cache.root.children[0].error == "下级文档不能越出当前文档所在目录"


def test_requires_agents_filename(tmp_path: Path) -> None:
    root = tmp_path / "index.md"
    write_document(root, "# index")

    with pytest.raises(DocumentTreeError, match="AGENTS.md"):
        build_document_cache(root)
