from pathlib import Path

import pytest

from context_router.services.workspace_paths import (
    WorkspacePathError,
    derive_agents_path,
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
    assert derive_agents_path("/workspace/company", "services/order") == (
        "/workspace/company/services/order/AGENTS.md"
    )


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(WorkspacePathError, match="越出工作空间"):
        resolve_project_root(workspace, "linked")
