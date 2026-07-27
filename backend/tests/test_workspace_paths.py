from pathlib import Path

import pytest

from context_router.services.workspace_paths import (
    WorkspacePathError,
    derive_agents_path,
    normalize_document_relative_path,
    normalize_project_relative_path,
    resolve_project_root,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (".", "."),
        ("./", "."),
        ("./services/order", "services/order"),
        ("services//order", "services/order"),
    ],
)
def test_normalizes_project_relative_path(value: str, expected: str) -> None:
    assert normalize_project_relative_path(value) == expected


@pytest.mark.parametrize("value", ["", "/absolute", "../outside", "a/../../outside", "~/repo"])
def test_rejects_unsafe_project_relative_path(value: str) -> None:
    with pytest.raises(WorkspacePathError):
        normalize_project_relative_path(value)


def test_derives_agents_path_from_workspace_and_project() -> None:
    assert derive_agents_path(
        "/workspace/company",
        "docs/backend/order/AGENTS.md",
    ) == ("/workspace/company/docs/backend/order/AGENTS.md")


@pytest.mark.parametrize(
    "value",
    ["AGENTS.md", "backend/order/AGENTS.md", "../AGENTS.md", "docs/order/README.md"],
)
def test_rejects_invalid_new_project_document_path(value: str) -> None:
    with pytest.raises(WorkspacePathError):
        normalize_document_relative_path(value, require_docs=True)


def test_allows_legacy_project_document_path_during_restore() -> None:
    assert (
        normalize_document_relative_path(
            "services/order/AGENTS.md",
            require_docs=False,
        )
        == "services/order/AGENTS.md"
    )


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePathError, match="越出工作空间"):
        resolve_project_root(workspace, "linked")
